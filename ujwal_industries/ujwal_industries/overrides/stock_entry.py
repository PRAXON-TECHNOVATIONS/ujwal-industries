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
    FINAL SCRAP VALIDATION (REMAINING-BASED)

    Rules:
    - Runs only when custom_is_scrap_entry = 1
    - Uses Work Order produced_qty
    - Allows under-scrap
    - Allows over-scrap within tolerance
    - Blocks only excessive over-scrap
    """

    if doc.get("purpose") != "Manufacture":
        return

    if not bool(getattr(doc, "custom_is_scrap_entry", 0)):
        return

    work_order = doc.get("work_order")
    bom_no = doc.get("bom_no")

    if not work_order or not bom_no:
        return

    scrap_items = _get_stock_entry_scrap_items(doc)
    if not scrap_items:
        return
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
    errors = []
    precision = frappe.get_precision("Stock Entry Detail", "qty") or 6

    for item_code, current_qty in scrap_items.items():

        bom_item = bom_data.get(item_code)
        if not bom_item:
            continue

        total_expected = flt(bom_item["qty"], precision)
        tolerance_pct = max(0, flt(bom_item["tolerance"]))

        already_done = flt(already_scrap_map.get(item_code, 0), precision)

        remaining = total_expected - already_done

        tolerance_qty = abs(remaining) * (tolerance_pct / 100)

        max_allowed = remaining + tolerance_qty

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