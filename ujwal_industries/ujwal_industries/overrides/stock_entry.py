# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from typing import Any, TypedDict, cast

import frappe
from frappe import _
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import flt


class BOMScrapData(TypedDict):
    """Type definition for BOM scrap item data."""

    qty: float
    tolerance: float


class BOMScrapRow(TypedDict):
    """Type definition for BOM scrap item SQL row."""

    item_code: str
    stock_qty: float
    tolerance: float


def stash_manually_set_rates(doc, method=None):
    stash = {}
    for item in doc.get("items"):
        if item.s_warehouse and item.get("set_basic_rate_manually") and flt(item.basic_rate):
            stash[item.idx] = flt(item.basic_rate)

    doc._manual_rates_stash = stash


def protect_manually_set_rates(doc, method=None):
    """validate: restore stashed rates and recalculate item-level fields."""
    stash = getattr(doc, "_manual_rates_stash", {})
    if not stash:
        return

    for item in doc.get("items"):
        if item.idx not in stash:
            continue

        rate = stash[item.idx]
        qty = flt(item.transfer_qty)
        add_cost = flt(item.additional_cost)

        item.basic_rate     = rate
        item.basic_amount   = flt(qty * rate, item.precision("basic_amount"))
        item.valuation_rate = rate + (add_cost / qty if qty else 0)
        item.amount         = item.basic_amount + add_cost
        item.taxable_value  = item.amount

        # item-level GST amounts
        item.cgst_amount = flt(item.taxable_value * flt(item.get("cgst_rate") or 0) / 100, 2)
        item.sgst_amount = flt(item.taxable_value * flt(item.get("sgst_rate") or 0) / 100, 2)
        item.igst_amount = flt(item.taxable_value * flt(item.get("igst_rate") or 0) / 100, 2)
        item.cess_amount = flt(item.taxable_value * flt(item.get("cess_rate") or 0) / 100, 2)

    doc.set_total_incoming_outgoing_value()
    doc.set_total_amount()


def finalize_manual_rate_taxes(doc, method=None):
    """
    before_save: runs AFTER india_compliance validate hooks.
    Recalculates taxes table + doc-level totals using corrected taxable_value.
    Only fires when at least one item has set_basic_rate_manually.
    """
    if not any(item.get("set_basic_rate_manually") for item in doc.get("items")):
        return

    total_taxable = flt(sum(flt(i.taxable_value) for i in doc.get("items")))
    running_total = total_taxable
    total_tax = 0.0

    for tax in doc.get("taxes"):
        tax_amt = flt(total_taxable * flt(tax.rate) / 100, 2)
        tax.tax_amount = tax_amt
        running_total = flt(running_total + tax_amt, 2)
        tax.base_total = running_total
        total_tax += tax_amt

    doc.total_taxes      = flt(total_tax, 2)
    doc.base_grand_total = flt(total_taxable + total_tax, 2)


@frappe.whitelist()
def get_bom_scrap_items(bom_no):
    if not bom_no:
        return []

    return frappe.get_all(
        "BOM Scrap Item",
        filters={
            "parent": bom_no,
            "parenttype": "BOM"
        },
        pluck="item_code"
    )
    
def validate_scrap_item_tolerance(doc: Document, method=None) -> None:
    """
    Unified Scrap Validation

    Case A: custom_is_scrap_entry = 1
        → Remaining-based, upper-limit-only logic

    Case B: custom_is_scrap_entry = 0
        → Old min-max tolerance logic (manufacture + scrap together)
    """

    if doc.get("purpose") != "Manufacture":
        return

    work_order = doc.get("work_order")
    bom_no = doc.get("bom_no")

    if not work_order or not bom_no:
        return

    scrap_items = _get_stock_entry_scrap_items(doc)
    if not scrap_items:
        return

    # CASE A — PURE SCRAP ENTRY
    if bool(getattr(doc, "custom_is_scrap_entry", 0)):

        produced_qty = flt(
            frappe.db.get_value("Work Order", work_order, "produced_qty")
        )

        if produced_qty <= 0:
            frappe.throw(
                _("Cannot create Scrap Entry because Produced Qty in Work Order is 0")
            )

        bom_data = _get_bom_scrap_items_with_tolerance(bom_no, produced_qty)
        if not bom_data:
            return

        already_booked = frappe.db.sql(
            """
            SELECT
                sed.item_code,
                SUM(sed.qty) AS qty
            FROM `tabStock Entry` se
            JOIN `tabStock Entry Detail` sed
                ON sed.parent = se.name
            WHERE
                se.work_order = %s
                AND se.docstatus = 1
                AND sed.is_scrap_item = 1
                AND se.name != %s
            GROUP BY sed.item_code
            """,
            (work_order, doc.name),
            as_dict=True,
        )

        already_scrap_map = {
            row.item_code: flt(row.qty) for row in already_booked
        }

        precision = frappe.get_precision("Stock Entry Detail", "qty") or 6
        errors = []

        for item_code, current_qty in scrap_items.items():
            bom_item = bom_data.get(item_code)
            if not bom_item:
                continue

            total_expected = flt(bom_item["qty"], precision)
            tolerance_pct = max(0, flt(bom_item["tolerance"]))
            already_done = flt(already_scrap_map.get(item_code, 0), precision)

            remaining = flt(total_expected - already_done, precision)
            if remaining < 0:
                remaining = 0

            max_allowed = remaining + (remaining * tolerance_pct / 100)

            if flt(current_qty, precision) > flt(max_allowed, precision):
                errors.append(
                    _(
                        "Scrap item {0}: qty {1} exceeds allowed remaining "
                        "{2} (Remaining: {3}, Tolerance: ±{4}%)"
                    ).format(
                        frappe.bold(item_code),
                        flt(current_qty, precision),
                        flt(max_allowed, precision),
                        flt(remaining, precision),
                        tolerance_pct,
                    )
                )

        if errors:
            frappe.throw(
                "<br>".join(errors),
                title=_("Scrap Quantity Tolerance Exceeded"),
            )

        return
    
    # CASE B — MANUFACTURE + SCRAP
    fg_completed_qty = flt(doc.get("fg_completed_qty"))
    if fg_completed_qty <= 0:
        return

    bom_data = _get_bom_scrap_items_with_tolerance(bom_no, fg_completed_qty)
    if not bom_data:
        return

    _validate_scrap_quantities(scrap_items, bom_data)

def _get_stock_entry_scrap_items(doc: Document) -> dict[str, float]:
    """
    Extract and aggregate scrap items from Stock Entry.

    Args:
        doc: Stock Entry document

    Returns:
        Dictionary mapping item_code to total quantity for all scrap items
    """
    scrap_items: dict[str, float] = {}
    items: list[Any] = list(doc.get("items") or [])
    for item in items:
        if item.is_scrap_item:
            item_code: str = item.item_code
            scrap_items[item_code] = scrap_items.get(item_code, 0) + flt(item.qty)
    return scrap_items

def _get_bom_scrap_items_with_tolerance(
    bom_no: str, fg_completed_qty: float
) -> dict[str, BOMScrapData]:
    """
    Fetch BOM scrap items with tolerance using single optimized query.

    Scales scrap qty proportionally to finished goods qty.

    Args:
        bom_no: BOM document name
        fg_completed_qty: Finished goods quantity being manufactured

    Returns:
        Dictionary mapping item_code to BOMScrapData with scaled qty and tolerance
    """
    bom_qty = flt(frappe.db.get_value("BOM", bom_no, "quantity")) or 1

    bom_scrap = cast(
        list[BOMScrapRow],
        frappe.db.sql(
            """
            SELECT
                item_code,
                stock_qty,
                IFNULL(custom_tolerance_, 0) as tolerance
            FROM
                `tabBOM Scrap Item`
            WHERE
                parent = %s
                AND parenttype = 'BOM'
            """,
            (bom_no,),
            as_dict=True,
        ),
    )

    bom_data: dict[str, BOMScrapData] = {}
    for item in bom_scrap:
        scaled_qty = flt(item["stock_qty"]) / bom_qty * flt(fg_completed_qty)
        bom_data[item["item_code"]] = BOMScrapData(
            qty=scaled_qty,
            tolerance=flt(item["tolerance"]),
        )
    return bom_data


def _validate_scrap_quantities(
    scrap_items: dict[str, float], bom_data: dict[str, BOMScrapData]
) -> None:
    """
    Validate each scrap item qty against BOM qty with tolerance.

    Args:
        scrap_items: Dictionary from _get_stock_entry_scrap_items()
        bom_data: Dictionary from _get_bom_scrap_items_with_tolerance()

    Raises:
        frappe.ValidationError: If any scrap item exceeds tolerance
    """
    errors: list[str] = []
    precision: int = frappe.get_precision("Stock Entry Detail", "qty") or 6

    for item_code, actual_qty in scrap_items.items():
        bom_item = bom_data.get(item_code)
        if not bom_item:
            # Item not in BOM scrap - could be from Job Card, skip validation
            continue

        expected_qty: float = bom_item["qty"]
        tolerance_pct: float = max(0.0, bom_item["tolerance"])  # Clamp negative values
        tolerance_qty: float = expected_qty * (tolerance_pct / 100)

        min_qty: float = flt(expected_qty - tolerance_qty, precision)
        max_qty: float = flt(expected_qty + tolerance_qty, precision)
        actual_qty_rounded: float = flt(actual_qty, precision)

        if actual_qty_rounded < min_qty or actual_qty_rounded > max_qty:
            errors.append(
                _("Scrap item {0}: qty {1} is outside allowed range {2} to {3} "
                  "(BOM qty: {4}, Tolerance: {5}%)").format(
                    frappe.bold(item_code),
                    actual_qty_rounded,
                    min_qty,
                    max_qty,
                    flt(expected_qty, precision),
                    tolerance_pct,
                )
            )

    if errors:
        frappe.throw(
            "<br>".join(errors),
            title=_("Scrap Quantity Tolerance Exceeded"),
        )