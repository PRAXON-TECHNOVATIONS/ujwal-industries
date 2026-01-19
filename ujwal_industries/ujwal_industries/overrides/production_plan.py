# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import frappe
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, getdate, now_datetime


def set_planned_start_dates(doc: Document, method: str | None = None) -> None:
    """
    Calculate planned_start_date for Production Plan items.

    Formula: planned_start_date = delivery_date - lead_time_days

    Called via doc_events hook on Production Plan before_save.
    Only applies when get_items_from = "Sales Order".

    For combine_items=True: Uses earliest delivery_date from all SOs.

    Args:
        doc: Production Plan document
        method: Event method name (unused, required for hook signature)
    """
    _ = method  # Unused but required for hook signature

    # Only process Sales Order-based plans
    if doc.get("get_items_from") != "Sales Order":
        return

    if not doc.get("po_items"):
        return

    combine_items = bool(doc.get("combine_items"))

    # BATCH FETCH: All delivery dates and lead times in 2-3 queries total
    delivery_cache, lead_time_cache = _batch_fetch_data(doc, combine_items)

    # Process each item using cached data - O(n)
    po_items: list[Any] = list(doc.get("po_items") or [])
    for po_item in po_items:
        try:
            delivery_date = _get_delivery_date_from_cache(
                po_item, combine_items, delivery_cache
            )
            lead_time_days = lead_time_cache.get(po_item.item_code, 0)

            if delivery_date:
                if lead_time_days > 0:
                    planned_date = add_days(delivery_date, -lead_time_days)
                else:
                    planned_date = delivery_date

                # Convert Date to Datetime (start of day)
                po_item.planned_start_date = _to_datetime(planned_date)
            else:
                po_item.planned_start_date = now_datetime()

        except Exception as e:
            frappe.log_error(
                message=f"Error calculating planned_start_date for {po_item.item_code}: {str(e)}",
                title="Production Plan Date Calculation",
            )
            po_item.planned_start_date = now_datetime()


@frappe.whitelist()
def calculate_planned_start_dates_client(production_plan: str) -> dict[str, Any]:
    """
    Client-callable method to calculate planned start dates.

    Called from client script after Get Items button is clicked.

    Args:
        production_plan: Production Plan document name

    Returns:
        Dictionary with calculated dates for each po_item
    """
    doc = frappe.get_doc("Production Plan", production_plan)

    if doc.get("get_items_from") != "Sales Order":
        return {}

    if not doc.get("po_items"):
        return {}

    combine_items = bool(doc.get("combine_items"))
    delivery_cache, lead_time_cache = _batch_fetch_data(doc, combine_items)

    results = {}
    po_items: list[Any] = list(doc.get("po_items") or [])

    for po_item in po_items:
        try:
            delivery_date = _get_delivery_date_from_cache(
                po_item, combine_items, delivery_cache
            )
            lead_time_days = lead_time_cache.get(po_item.item_code, 0)

            if delivery_date:
                if lead_time_days > 0:
                    planned_date = add_days(delivery_date, -lead_time_days)
                else:
                    planned_date = delivery_date

                planned_datetime = _to_datetime(planned_date)
            else:
                planned_datetime = now_datetime()

            # Store result by item name
            results[po_item.name] = str(planned_datetime)

        except Exception:
            results[po_item.name] = str(now_datetime())

    return results


def _batch_fetch_data(doc: Document, combine_items: bool) -> tuple[dict[str, Any], dict[str, int]]:
    """
    Batch fetch all delivery dates and lead times.

    Performance: 2-3 queries total regardless of number of items.

    Args:
        doc: Production Plan document
        combine_items: Whether items are combined by BOM

    Returns:
        Tuple of (delivery_date_cache, lead_time_cache)
    """
    delivery_cache: dict[str, Any] = {}

    if combine_items:
        # When combine_items is True, get all items from the Sales Orders in sales_orders table
        # Find MIN delivery date per item_code across all SO items
        ref_data = frappe.db.sql(
            """
            SELECT
                soi.item_code,
                MIN(COALESCE(soi.delivery_date, so.delivery_date)) as delivery_date
            FROM `tabProduction Plan Sales Order` ppso
            INNER JOIN `tabSales Order` so ON so.name = ppso.sales_order
            INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
            WHERE ppso.parent = %s AND ppso.parenttype = 'Production Plan'
            GROUP BY soi.item_code
        """,
            (doc.name,),
            as_dict=True,
        )

        # Build cache by item_code (since combine_items groups by item_code/BOM)
        for row in ref_data:
            delivery_cache[row.item_code] = row.delivery_date

    else:
        # Batch fetch SO Item delivery dates
        po_items_list: list[Any] = list(doc.get("po_items") or [])
        so_items = [pi.sales_order_item for pi in po_items_list if pi.sales_order_item]

        if so_items:
            so_item_data = frappe.db.sql(
                """
                SELECT soi.name, COALESCE(soi.delivery_date, so.delivery_date) as delivery_date
                FROM `tabSales Order Item` soi
                LEFT JOIN `tabSales Order` so ON so.name = soi.parent
                WHERE soi.name IN %s
            """,
                (so_items,),
                as_dict=True,
            )

            for row in so_item_data:
                delivery_cache[row.name] = row.delivery_date

    # Batch fetch lead times
    po_items_list = list(doc.get("po_items") or [])
    item_codes = list(set([pi.item_code for pi in po_items_list]))
    lead_time_cache: dict[str, int] = {}

    if item_codes:
        item_data = frappe.db.get_all(
            "Item", filters={"name": ["in", item_codes]}, fields=["name", "lead_time_days"]
        )

        for row in item_data:
            lead_time_cache[row.name] = int(row.lead_time_days or 0)

    return delivery_cache, lead_time_cache


def _get_delivery_date_from_cache(
    po_item: Document, combine_items: bool, cache: dict[str, Any]
) -> Optional[Any]:
    """
    Get delivery date from cache based on combine mode.

    Args:
        po_item: Production Plan Item
        combine_items: Whether items are combined
        cache: Delivery date cache dict

    Returns:
        Delivery date or None
    """
    if combine_items:
        # When combined, cache is keyed by item_code (earliest date for that item)
        return cache.get(po_item.item_code)
    else:
        # When not combined, cache is keyed by sales_order_item (specific SO item)
        return cache.get(po_item.sales_order_item)


def _to_datetime(date_value: Any) -> datetime:
    """
    Convert Date to Datetime at start of day (00:00:00).

    Args:
        date_value: Date object or string

    Returns:
        Datetime object set to start of day
    """
    if not date_value:
        return now_datetime()

    date_obj = getdate(date_value)
    return datetime.combine(date_obj, datetime.min.time())
