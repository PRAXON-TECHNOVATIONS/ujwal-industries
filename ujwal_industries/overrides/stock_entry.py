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


def validate_scrap_item_tolerance(doc: Document, method: str | None = None) -> None:
    """
    Validate scrap item quantities against BOM-defined tolerance.

    Called via doc_events hook on Stock Entry validate.
    Only applies to Manufacture entries with a work order.

    Args:
        doc: Stock Entry document
        method: Event method name (unused, required for hook signature)
    """
    _ = method  # Unused but required for hook signature

    purpose = doc.get("purpose")
    work_order = doc.get("work_order")
    bom_no = doc.get("bom_no")

    if purpose != "Manufacture" or not work_order or not bom_no:
        return

    # Get scrap items from Stock Entry (O(n) single pass)
    scrap_items = _get_stock_entry_scrap_items(doc)
    if not scrap_items:
        return

    # Fetch BOM scrap items with tolerance (single query)
    fg_completed_qty = doc.get("fg_completed_qty")
    bom_data = _get_bom_scrap_items_with_tolerance(
        cast(str, bom_no),
        cast(float, fg_completed_qty),
    )
    if not bom_data:
        return

    # Validate quantities
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
