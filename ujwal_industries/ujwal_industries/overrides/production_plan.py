# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

import frappe
from frappe import _
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, add_to_date, getdate, get_datetime, now_datetime


def _get_allow_backdated_setting() -> bool:
    """
    Get the allow_backdated_planned_start_date setting from Manufacturing Settings.

    Returns:
        True if backdated dates are allowed (default), False otherwise.
    """
    allow_backdated = frappe.db.get_single_value(
        "Manufacturing Settings", "allow_backdated_planned_start_date"
    )
    # Default to True if field doesn't exist yet
    return bool(allow_backdated) if allow_backdated is not None else True


def _adjust_date_if_backdated(date_value: datetime | None) -> datetime | None:
    """
    Adjust the date to today if backdated dates are not allowed and the date is in the past.

    Args:
        date_value: The calculated date (datetime or None)

    Returns:
        The original date if backdated dates are allowed or date is not in past,
        otherwise returns now_datetime() (today's datetime).
    """
    if date_value is None:
        return None

    if _get_allow_backdated_setting():
        return date_value

    today = getdate()
    date_only = getdate(date_value)

    if date_only < today:
        return now_datetime()

    return date_value


def validate_planned_start_dates(doc: Document, method: str | None = None) -> None:
    """
    Validate and auto-adjust dates if backdated dates are not allowed.

    Validates all date fields across:
    - po_items (FG): planned_start_date
    - sub_assembly_items (SFG): schedule_date
    - mr_items: custom_start_date

    Checks Manufacturing Settings.allow_backdated_planned_start_date field.
    If unchecked (0):
    - In House items: Auto-adjust backdated dates to today (smart behavior)
    - Subcontract/other items: Throw validation error for backdated dates

    Args:
        doc: Production Plan document
        method: Hook method name (unused)
    """
    del method  # Unused but required for hook signature

    # During import: persist flag so future saves also skip date logic
    if frappe.flags.in_import:
        doc.custom_skip_date_calculation = 1
        return

    # If user dates were preserved (e.g. from import), skip all date logic
    if doc.get("custom_skip_date_calculation"):
        return

    # If backdated dates are allowed (default), skip validation
    if _get_allow_backdated_setting():
        return

    today = getdate()
    today_datetime = now_datetime()

    # 1. Validate po_items (FG) - planned_start_date
    for row in doc.get("po_items") or []:
        if row.planned_start_date:
            planned_date = getdate(row.planned_start_date)

            if planned_date < today:
                manufacturing_type = row.get("custom_manufacturing_type") or ""

                if manufacturing_type == "In House":
                    # In House: handled by master_set_fg_dates_by_type with proper calculation
                    pass
                else:
                    # Subcontract/Other: Throw validation error
                    frappe.throw(
                        msg=_(
                            "FG Row #{0} ({1}): Planned Start Date ({2}) cannot be a past date. "
                            "Please select a date on or after today ({3})."
                        ).format(
                            row.idx,
                            row.item_code,
                            frappe.format(planned_date, "Date"),
                            frappe.format(today, "Date")
                        ),
                        title=_("Invalid Planned Start Date - FG Item")
                    )

    # 2. Validate sub_assembly_items (SFG) - schedule_date
    # SFG items are handled by set_subcontracting_suppliers with smart adjustment
    # No error thrown here - before_save will auto-adjust dates

    # 3. Validate mr_items - custom_start_date
    # MR items are handled by before_save with smart adjustment
    # No error thrown here - before_save will auto-adjust dates


def master_set_fg_dates_by_type(doc: Document, method: str | None = None) -> None:
    """
    MASTER FUNCTION: Updates Planned Start Date based on Manufacturing Type.
    
    Logic Update:
    1. Subcontract:
       - Check if user selected a 'custom_supplier'.
       - If YES: Fetch Lead Time for THAT supplier.
       - If NO: Fetch Default Supplier & Lead Time. Auto-populate field.
       - Date = Delivery Date - Lead Time.
       
    2. In House:
       - Clear Supplier field.
       - Date = Delivery Date - BOM Production Time.
    """
    
    # Skip all date logic during import or when user dates were manually preserved
    if frappe.flags.in_import or doc.get("custom_skip_date_calculation"):
        return

    if not doc.get("po_items"):
        return

    # If there are sub_assembly_items, FG dates should be driven by SFG dates
    # (via "Update FG from Sub-Assembly" button), not recalculated here
    if doc.get("sub_assembly_items"):
        return

    # Filter rows
    target_rows = [
        row for row in doc.po_items
        if row.get("custom_manufacturing_type") in ["Subcontract", "In House"]
    ]

    if not target_rows:
        return

    combine_items = bool(doc.get("combine_items"))
    
    # A. Delivery Dates
    delivery_cache = _batch_fetch_delivery_dates(doc, combine_items)
    
    # B. BOM Times (For In House)
    bom_time_cache = _batch_fetch_bom_operations(doc)
    
    # C. Supplier Cache
    sub_items = [r.item_code for r in target_rows if r.get("custom_manufacturing_type") == "Subcontract"]
    item_supplier_data = {}
    
    if sub_items:
        # Fetch ALL supplier mappings for these items
        raw_data = frappe.db.sql("""
            SELECT parent as item_code, supplier, lead_time_days, is_default 
            FROM `tabItem Subcontracting Supplier`
            WHERE parent IN %(items)s
        """, {"items": list(set(sub_items))}, as_dict=True)
        
        # Group data by Item Code
        for d in raw_data:
            if d.item_code not in item_supplier_data:
                item_supplier_data[d.item_code] = []
            item_supplier_data[d.item_code].append(d)


    # --- 2. MAIN LOGIC LOOP ---
    for row in target_rows:
        try:
            mfg_type = row.get("custom_manufacturing_type")
            
            # Delivery Date logic
            delivery_date = _get_delivery_date_from_cache(row, combine_items, delivery_cache)
            if not delivery_date: continue
            
            delivery_dt_obj = get_datetime(delivery_date)

            # === SUBCONTRACT LOGIC ===
            if mfg_type == "Subcontract":
                available_suppliers = item_supplier_data.get(row.item_code, [])

                target_supplier_row = None

                if row.custom_supplier:
                    target_supplier_row = next((s for s in available_suppliers if s.supplier == row.custom_supplier), None)

                if not target_supplier_row:
                    target_supplier_row = next((s for s in available_suppliers if s.is_default), None)

                    if target_supplier_row:
                        row.custom_supplier = target_supplier_row.supplier

                lead_time = int(target_supplier_row.lead_time_days) if target_supplier_row else 0

                new_date = add_days(getdate(delivery_dt_obj), -lead_time)
                row.planned_start_date = _adjust_date_if_backdated(_to_datetime(new_date))

            # === IN HOUSE LOGIC ===
            elif mfg_type == "In House":
                row.custom_supplier = None # Clear Supplier

                prod_minutes = _calculate_production_minutes(
                    row.bom_no, row.planned_qty, bom_time_cache
                )

                if prod_minutes > 0:
                    calculated_date = _subtract_minutes_from_datetime(
                        delivery_dt_obj, prod_minutes
                    )

                    # Check if backdated and show informative message
                    if not _get_allow_backdated_setting():
                        today = getdate()
                        calculated_date_only = getdate(calculated_date)

                        if calculated_date_only < today:
                            # Calculate production days needed
                            prod_days = prod_minutes / (60 * 24)

                            # Extended delivery = today + production_time
                            extended_delivery = add_days(today, math.ceil(prod_days))

                            # planned_start_date = extended_delivery - production_time
                            # This equals today at 00:00:00
                            new_planned_start = _subtract_minutes_from_datetime(
                                _to_datetime(extended_delivery), prod_minutes
                            )

                            # Days delivery needs to be extended
                            current_delivery = getdate(delivery_dt_obj)
                            extension_days = (getdate(extended_delivery) - current_delivery).days

                            frappe.msgprint(
                                msg=_(
                                    "Row #{0} ({1}):<br>"
                                    "• Production time required: <b>{2:.1f} days</b> ({3:,.0f} minutes)<br>"
                                    "• Original delivery date: <b>{4}</b><br>"
                                    "• Extended delivery date: <b>{5}</b> (+{6} days)<br><br>"
                                    "📅 Planned Start Date set to: <b>{7}</b>"
                                ).format(
                                    row.idx,
                                    row.item_code,
                                    prod_days,
                                    prod_minutes,
                                    frappe.format(current_delivery, "Date"),
                                    frappe.format(extended_delivery, "Date"),
                                    extension_days if extension_days > 0 else 0,
                                    frappe.format(getdate(new_planned_start), "Date")
                                ),
                                title=_("Production Schedule Alert"),
                                indicator="orange"
                            )

                            row.planned_start_date = new_planned_start
                        else:
                            row.planned_start_date = calculated_date
                    else:
                        row.planned_start_date = calculated_date
                else:
                    row.planned_start_date = _adjust_date_if_backdated(delivery_dt_obj)

        except Exception as e:
            frappe.log_error(f"Master Date Logic Error: {str(e)}")
 
@frappe.whitelist()
def get_item_suppliers_query(doctype, txt, searchfield, start, page_len, filters):
    """
    Returns a list of Suppliers specifically linked to an Item.
    Used by JavaScript to filter the dropdown.
    """
    if not filters or not filters.get("item_code"):
        return []

    return frappe.db.sql("""
        SELECT supplier
        FROM `tabItem Subcontracting Supplier`
        WHERE parent = %(item_code)s
        AND supplier LIKE %(txt)s
        ORDER BY is_default DESC
        LIMIT %(start)s, %(page_len)s
    """, {
        "item_code": filters.get("item_code"),
        "txt": f"%{txt}%",
        "start": start,
        "page_len": page_len
    })
    
@frappe.whitelist()
def get_subcontract_updates_client(item_code: str, company: str, sales_order_item: str | None = None) -> dict[str, Any]:
    """
    JS Helper: Returns Default Supplier AND Calculated Planned Start Date.
    """
    # 1. Fetch Supplier & Lead Time
    supp_data = frappe.db.get_value("Item Subcontracting Supplier",
        {"parent": item_code, "company": company, "is_default": 1},
        ["supplier", "lead_time_days"], as_dict=True
    )
    
    if not supp_data:
        return {}

    result = {
        "custom_supplier": supp_data.supplier
    }

    # 2. Fetch Delivery Date
    if sales_order_item:
        # Try fetching specific SO Item delivery date, fallback to parent SO date
        delivery_date = frappe.db.get_value("Sales Order Item", sales_order_item, "delivery_date")
        
        if not delivery_date:
            so_name = frappe.db.get_value("Sales Order Item", sales_order_item, "parent")
            if so_name:
                delivery_date = frappe.db.get_value("Sales Order", so_name, "delivery_date")
        
        # 3. Calculate Date (Delivery - Lead Time)
        if delivery_date:
            lead_time = int(supp_data.lead_time_days or 0)
            new_date = add_days(getdate(delivery_date), -lead_time)
            result["planned_start_date"] = str(_to_datetime(new_date))

    return result
    
def onload_production_plan(doc: Document, method: str | None = None) -> None:
    """
    Store original sub-assembly schedule_dates and MR item dates in __onload for comparison.
    This allows detecting user changes and calculating deltas for SFG/FG date updates.
    """
    del method  # Unused but required for hook signature

    # Store original sub-assembly schedule dates
    if doc.get("sub_assembly_items"):
        original_dates = {}
        for row in doc.sub_assembly_items:
            if row.production_item and row.schedule_date:
                original_dates[row.name] = {
                    "production_item": row.production_item,
                    "parent_item_code": row.parent_item_code,
                    "schedule_date": str(row.schedule_date),
                    "custom_schedule_end_date": str(row.custom_schedule_end_date) if row.custom_schedule_end_date else None,
                    "type_of_manufacturing": row.type_of_manufacturing
                }
        doc.set_onload("original_subassembly_dates", original_dates)

    # Store original MR item dates
    if doc.get("mr_items"):
        original_mr_dates = {}
        for row in doc.mr_items:
            # Store if either custom_start_date or schedule_date exists
            has_custom_start = hasattr(row, 'custom_start_date') and row.custom_start_date
            has_schedule = row.schedule_date
            if row.item_code and (has_custom_start or has_schedule):
                original_mr_dates[row.name] = {
                    "item_code": row.item_code,
                    "custom_start_date": str(row.custom_start_date) if has_custom_start else None,
                    "schedule_date": str(row.schedule_date) if has_schedule else None
                }
        doc.set_onload("original_mr_dates", original_mr_dates)


@frappe.whitelist()
def refresh_original_mr_dates(
    production_plan_name: str,
    mr_items_data: list[dict[str, Any]] | str
) -> dict[str, dict[str, Any]]:
    """
    Refresh original_mr_dates based on current client-side MR items data.

    Call this after "Get Items for Material Request" is clicked and dates are calculated,
    so subsequent comparisons work correctly.

    Args:
        production_plan_name: Name of the Production Plan
        mr_items_data: Current MR items from client with their calculated dates

    Returns:
        Dict mapping row.name to date info
    """
    import json

    if isinstance(mr_items_data, str):
        mr_items_data = json.loads(mr_items_data)

    original_dates = {}
    for item_info in mr_items_data:
        row_name = item_info.get("name")
        item_code = item_info.get("item_code")
        custom_start_date = item_info.get("custom_start_date")
        schedule_date = item_info.get("schedule_date")

        if item_code and (custom_start_date or schedule_date):
            key = row_name if row_name else item_code
            original_dates[key] = {
                "item_code": item_code,
                "custom_start_date": str(custom_start_date) if custom_start_date else None,
                "schedule_date": str(schedule_date) if schedule_date else None
            }

    return original_dates


@frappe.whitelist()
def refresh_original_subassembly_dates(
    production_plan_name: str,
    subassembly_data: list[dict[str, Any]] | str
) -> dict[str, dict[str, Any]]:
    """
    Refresh original_subassembly_dates based on current client-side data.

    Call this after "Get Sub Assembly Items" is clicked and dates are calculated,
    so subsequent comparisons work correctly.

    Args:
        production_plan_name: Name of the Production Plan
        subassembly_data: Current sub-assembly items from client with their calculated dates

    Returns:
        Dict mapping row.name (or production_item as fallback) to date info
    """
    import json

    if isinstance(subassembly_data, str):
        subassembly_data = json.loads(subassembly_data)

    original_dates = {}
    for item_info in subassembly_data:
        row_name = item_info.get("name")
        prod_item = item_info.get("production_item")
        schedule_date = item_info.get("schedule_date")

        if prod_item and schedule_date:
            key = row_name if row_name else prod_item
            original_dates[key] = {
                "production_item": prod_item,
                "parent_item_code": item_info.get("parent_item_code"),
                "schedule_date": str(schedule_date) if schedule_date else None,
                "custom_schedule_end_date": str(item_info.get("custom_schedule_end_date")) if item_info.get("custom_schedule_end_date") else None,
                "type_of_manufacturing": item_info.get("type_of_manufacturing")
            }

    return original_dates


def set_planned_start_dates(doc: Document, method: str | None = None) -> None:
    """
    Calculate planned_start_date for Production Plan items with exact datetime precision.

    Formula: planned_start_date = delivery_datetime - production_time_minutes

    Production time is calculated from BOM operations:
    - For each operation: time_per_unit = time_in_mins / custom_batchsize
    - Total time for operation = time_per_unit × planned_qty
    - Sum all operations (in minutes) and subtract from delivery datetime

    Called via doc_events hook on Production Plan before_save.
    Only applies when get_items_from = "Sales Order".

    Logic for determining when to calculate:
    - If planned_start_date is None → calculate
    - If planned_start_date was auto-set by ERPNext (same day, close to now) → calculate
    - If user manually changed the date → preserve

    For combine_items=True: Uses earliest delivery_date from all SOs.

    Args:
        doc: Production Plan document
        method: Event method name (unused, required for hook signature)
    """
    del method  # Unused but required for hook signature

    # Skip all date logic during import or when user dates were manually preserved
    if frappe.flags.in_import or doc.get("custom_skip_date_calculation"):
        return

    # Only process Sales Order-based plans
    if doc.get("get_items_from") != "Sales Order":
        return

    if not doc.get("po_items"):
        return

    # If sub_assembly_items exist, FG dates are driven by SFG dates
    # Don't recalculate FG dates here - they're set via "Update FG from Sub-Assembly"
    if doc.get("sub_assembly_items"):
        return

    combine_items = bool(doc.get("combine_items"))

    # BATCH FETCH: All delivery dates and BOM operation times
    delivery_cache = _batch_fetch_delivery_dates(doc, combine_items)
    bom_time_cache = _batch_fetch_bom_operations(doc)

    # Process each item using cached data - O(n)
    po_items: list[Any] = list(doc.get("po_items") or [])
    for po_item in po_items:
        try:
            delivery_date = _get_delivery_date_from_cache(
                po_item, combine_items, delivery_cache
            )

            # Calculate production time in minutes based on BOM operations
            production_minutes = _calculate_production_minutes(
                po_item.bom_no,
                po_item.planned_qty,
                bom_time_cache
            )

            if delivery_date:
                # Convert delivery_date to datetime and subtract production time
                delivery_datetime = get_datetime(delivery_date)
                if production_minutes > 0:
                    calculated_datetime = _subtract_minutes_from_datetime(
                        delivery_datetime, production_minutes
                    )
                else:
                    calculated_datetime = delivery_datetime
            else:
                calculated_datetime = None

            # Determine if we should set/override the date
            should_set_date = _should_override_planned_date(
                po_item.planned_start_date, calculated_datetime
            )

            if should_set_date and calculated_datetime:
                po_item.planned_start_date = _adjust_date_if_backdated(calculated_datetime)
            elif not po_item.planned_start_date:
                # Fallback if no calculated date and no existing date
                po_item.planned_start_date = now_datetime()

        except Exception as e:
            frappe.log_error(
                message=f"Error calculating planned_start_date for {po_item.item_code}: {str(e)}",
                title="Production Plan Date Calculation",
            )
            if not po_item.planned_start_date:
                po_item.planned_start_date = now_datetime()


def _should_override_planned_date(
    current_date: datetime | None, calculated_date: datetime | None
) -> bool:
    """
    Determine if we should override the current planned_start_date.

    Returns True if:
    - current_date is None (no date set)
    - current_date appears to be auto-set by ERPNext (today's date, close to now)

    Returns False if:
    - current_date appears to be manually set by user (different day or matches calculated)

    Args:
        current_date: Current planned_start_date value
        calculated_date: Our calculated date based on delivery_date - lead_time

    Returns:
        True if we should set/override the date
    """
    if not current_date:
        return True

    if not calculated_date:
        return False

    # Get current date as date object for comparison
    current_date_obj = getdate(current_date)
    calculated_date_obj = getdate(calculated_date)
    today = getdate(now_datetime())

    # If current date equals our calculated date, no need to change
    if current_date_obj == calculated_date_obj:
        return False

    # If current date is today (ERPNext auto-sets now_datetime()), override it
    # This catches the case where ERPNext's get_items sets now_datetime()
    if current_date_obj == today:
        return True

    # Otherwise, assume user set it manually - preserve it
    return False


@frappe.whitelist()
def calculate_planned_start_dates_client(production_plan: str) -> dict[str, Any]:
    """
    Client-callable method to calculate planned start dates.

    Called from client script after Get Items button is clicked.
    Returns calculated dates - client decides whether to apply them.

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
    delivery_cache = _batch_fetch_delivery_dates(doc, combine_items)
    bom_time_cache = _batch_fetch_bom_operations(doc)

    results = {}
    po_items: list[Any] = list(doc.get("po_items") or [])

    for po_item in po_items:
        try:
            delivery_date = _get_delivery_date_from_cache(
                po_item, combine_items, delivery_cache
            )
            production_minutes = _calculate_production_minutes(
                po_item.bom_no,
                po_item.planned_qty,
                bom_time_cache
            )

            if delivery_date:
                delivery_datetime = get_datetime(delivery_date)
                if production_minutes > 0:
                    planned_datetime = _subtract_minutes_from_datetime(
                        delivery_datetime, production_minutes
                    )
                else:
                    planned_datetime = delivery_datetime
            else:
                planned_datetime = now_datetime()

            # Adjust date if backdated dates are not allowed
            planned_datetime = _adjust_date_if_backdated(planned_datetime)

            # Store result by item name AND item_code for flexibility
            results[po_item.name] = {
                "planned_start_date": str(planned_datetime),
                "item_code": po_item.item_code,
                "production_minutes": production_minutes,
            }

        except Exception:
            results[po_item.name] = {
                "planned_start_date": str(now_datetime()),
                "item_code": po_item.item_code,
                "production_minutes": 0,
            }

    return results


@frappe.whitelist()
def calculate_planned_start_dates_realtime(
    item_codes: list[str] | str,
    sales_orders: list[str] | str,
    bom_data: dict[str, Any] | str = "{}",
    combine_items: int | str = 0
) -> dict[str, Any]:
    """
    Calculate planned_start_dates for items without requiring a saved Production Plan.

    This is called from client-side after "Get Items" to provide real-time date calculation.
    It queries the Sales Orders directly using the provided SO names.

    Args:
        item_codes: List of item codes to calculate dates for
        sales_orders: List of Sales Order names
        bom_data: Dictionary mapping item_code to {bom_no, planned_qty}
        combine_items: Whether items are combined (1 or 0)

    Returns:
        Dictionary keyed by item_code with calculated dates
    """
    import json

    # Handle JSON string input from client
    if isinstance(item_codes, str):
        item_codes = json.loads(item_codes)
    if isinstance(sales_orders, str):
        sales_orders = json.loads(sales_orders)
    if isinstance(bom_data, str):
        bom_data = json.loads(bom_data)

    combine_items_bool = bool(int(combine_items))

    if not item_codes or not sales_orders:
        return {}

    # Fetch delivery dates from Sales Orders
    delivery_cache: dict[str, Any] = {}

    if combine_items_bool:
        # Get minimum delivery date per item_code across all SOs
        delivery_data = frappe.db.sql(
            """
            SELECT
                soi.item_code,
                MIN(COALESCE(soi.delivery_date, so.delivery_date)) as delivery_date
            FROM `tabSales Order` so
            INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
            WHERE so.name IN %(sales_orders)s
              AND soi.item_code IN %(item_codes)s
            GROUP BY soi.item_code
        """,
            {"sales_orders": sales_orders, "item_codes": item_codes},
            as_dict=True,
        )

        for row in delivery_data:
            delivery_cache[row.item_code] = row.delivery_date
    else:
        # For non-combined, still get earliest date per item as fallback
        delivery_data = frappe.db.sql(
            """
            SELECT
                soi.item_code,
                MIN(COALESCE(soi.delivery_date, so.delivery_date)) as delivery_date
            FROM `tabSales Order` so
            INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
            WHERE so.name IN %(sales_orders)s
              AND soi.item_code IN %(item_codes)s
            GROUP BY soi.item_code
        """,
            {"sales_orders": sales_orders, "item_codes": item_codes},
            as_dict=True,
        )

        for row in delivery_data:
            delivery_cache[row.item_code] = row.delivery_date

    # Get default BOMs and quantities for items if not provided
    item_bom_map: dict[str, dict[str, Any]] = {}

    # First, use provided bom_data if available
    for ic in item_codes:
        if ic in bom_data and bom_data[ic].get("bom_no"):
            item_bom_map[ic] = {
                "bom_no": bom_data[ic]["bom_no"],
                "planned_qty": float(bom_data[ic].get("planned_qty", 0))
            }

    # For items without BOM data, fetch default active BOM
    # Note: This is a fallback - normally bom_data should be provided by the client
    items_without_bom = [ic for ic in item_codes if ic not in item_bom_map]
    if items_without_bom:
        try:
            bom_defaults = frappe.db.sql(
                """
                SELECT
                    item,
                    name as bom_no
                FROM `tabBOM`
                WHERE item IN %(items)s
                  AND is_active = 1
                  AND is_default = 1
            """,
                {"items": items_without_bom},
                as_dict=True,
            )

            for bom_row in bom_defaults:
                item_bom_map[bom_row.item] = {
                    "bom_no": bom_row.bom_no,
                    "planned_qty": 1.0  # Default to 1 if not specified
                }
        except Exception as e:
            frappe.log_error(
                message=f"Error fetching default BOMs: {str(e)}",
                title="Production Plan Realtime Calculation"
            )

    # Fetch BOM operations for all BOMs
    bom_nos = [item_bom_map[ic]["bom_no"] for ic in item_codes if ic in item_bom_map]
    bom_time_cache: dict[str, list[dict[str, Any]]] = {}

    if bom_nos:
        operations_data = frappe.db.sql(
            """
            SELECT
                parent as bom_no,
                time_in_mins,
                custom_batchsize,
                operation,
                idx
            FROM `tabBOM Operation`
            WHERE parent IN %(bom_nos)s
            ORDER BY parent, idx
        """,
            {"bom_nos": bom_nos},
            as_dict=True,
        )

        for op in operations_data:
            if op.bom_no not in bom_time_cache:
                bom_time_cache[op.bom_no] = []
            bom_time_cache[op.bom_no].append(op)

    # Calculate dates for each item
    results: dict[str, Any] = {}
    for item_code in item_codes:
        delivery_date = delivery_cache.get(item_code)

        # Get BOM and qty for this item
        bom_info = item_bom_map.get(item_code, {})
        bom_no = bom_info.get("bom_no")
        planned_qty = float(bom_info.get("planned_qty", 0))

        production_minutes = _calculate_production_minutes(bom_no, planned_qty, bom_time_cache) if bom_no else 0.0

        if delivery_date:
            delivery_datetime = get_datetime(delivery_date)
            if production_minutes > 0:
                planned_datetime = _subtract_minutes_from_datetime(
                    delivery_datetime, production_minutes
                )
            else:
                planned_datetime = delivery_datetime
        else:
            planned_datetime = now_datetime()

        results[item_code] = {
            "planned_start_date": str(planned_datetime),
            "delivery_date": str(delivery_date) if delivery_date else None,
            "production_minutes": production_minutes,
        }

    return results


@frappe.whitelist()
def calculate_inhouse_schedule_dates(
    production_plan_name: str,
    fg_dates: dict[str, Any] | str,
    inhouse_items: list[dict[str, Any]] | str
) -> dict[str, Any]:
    """
    Calculate schedule dates for In House sub-assembly items in real-time.

    Called from client-side JavaScript to provide immediate feedback when
    Get Sub Assembly Items is clicked.

    IMPORTANT: The items list must be in BOM traversal order (parent before children)
    so that parent dates are calculated before children need them.

    Args:
        production_plan_name: Production Plan document name
        fg_dates: Dict mapping FG item_code to planned_start_date
        inhouse_items: List of In House items with bom_no and qty (MUST be in order!)

    Returns:
        Dict mapping row name to {schedule_date, custom_schedule_end_date}
    """
    import json

    # Handle JSON string input
    if isinstance(fg_dates, str):
        fg_dates = json.loads(fg_dates)
    if isinstance(inhouse_items, str):
        inhouse_items = json.loads(inhouse_items)

    if not inhouse_items:
        return {}

    # Fetch BOM operations for all In House items
    bom_nos = [item["bom_no"] for item in inhouse_items if item.get("bom_no")]
    bom_time_cache: dict[str, list[dict[str, Any]]] = {}

    if bom_nos:
        operations_data = frappe.db.sql(
            """
            SELECT
                parent as bom_no,
                time_in_mins,
                custom_batchsize,
                operation,
                idx
            FROM `tabBOM Operation`
            WHERE parent IN %(bom_nos)s
            ORDER BY parent, idx
        """,
            {"bom_nos": bom_nos},
            as_dict=True,
        )

        for op in operations_data:
            if op.bom_no not in bom_time_cache:
                bom_time_cache[op.bom_no] = []
            bom_time_cache[op.bom_no].append(op)

    # Track schedule_date for each production_item as we process
    # This includes BOTH In House items AND their parents (which might be Subcontract or other In House)
    schedule_date_map: dict[str, Any] = {}

    # Initialize with FG dates
    for fg_item, fg_date in fg_dates.items():
        schedule_date_map[fg_item] = get_datetime(fg_date)

    # Process all items IN ORDER
    # For Subcontract items: just track their schedule_date for children to use
    # For In House items: calculate schedule_date and return it
    results: dict[str, Any] = {}

    for item_info in inhouse_items:
        parent_item = item_info["parent_item_code"]
        item_type = item_info.get("type_of_manufacturing", "In House")

        # Get base date: from schedule_date_map (which includes FG dates and Subcontract items)
        if parent_item in schedule_date_map:
            base_date = schedule_date_map[parent_item]
        else:
            # Parent not found - this shouldn't happen if items are in correct order
            # Log a warning and use the FG date or now as fallback
            frappe.log_error(
                message=f"Parent item {parent_item} not found in schedule_date_map for {item_info['production_item']}. Items may not be in correct order.",
                title="In House Schedule Date Calculation Warning"
            )
            # Try to find any FG date as fallback
            if fg_dates:
                base_date = get_datetime(list(fg_dates.values())[0])
            else:
                base_date = now_datetime()

        if item_type == "Subcontract":
            # For Subcontract items, use their existing schedule_date
            # (already calculated by client-side)
            if item_info.get("schedule_date"):
                schedule_date = get_datetime(item_info["schedule_date"])
                # Track for children to use
                schedule_date_map[item_info["production_item"]] = schedule_date
            # Don't add to results - we don't need to update Subcontract items
        else:
            # In House item - calculate based on BOM operations
            production_minutes = _calculate_production_minutes(
                item_info["bom_no"],
                float(item_info.get("qty", 0)),
                bom_time_cache
            )

            if production_minutes > 0:
                calculated_schedule_date = _subtract_minutes_from_datetime(base_date, production_minutes)

                # Check if backdated and handle smart adjustment
                if not _get_allow_backdated_setting():
                    today = getdate()
                    calculated_date_only = getdate(calculated_schedule_date)

                    if calculated_date_only < today:
                        # Calculate production days needed
                        prod_days = production_minutes / (60 * 24)

                        # Extended end date = today + production_time
                        extended_end_date = add_days(today, math.ceil(prod_days))

                        # schedule_date = extended_end_date - production_time
                        schedule_date = _subtract_minutes_from_datetime(
                            _to_datetime(extended_end_date), production_minutes
                        )
                        custom_schedule_end_date = _to_datetime(extended_end_date)
                    else:
                        schedule_date = calculated_schedule_date
                        custom_schedule_end_date = base_date
                else:
                    schedule_date = calculated_schedule_date
                    custom_schedule_end_date = base_date
            else:
                schedule_date = base_date
                custom_schedule_end_date = base_date

            # Store result (only for In House items)
            results[item_info["name"]] = {
                "schedule_date": str(schedule_date),
                "custom_schedule_end_date": str(custom_schedule_end_date)
            }

            # Track for children - store the SCHEDULE_DATE (when production starts)
            # so children can use it as their end date
            schedule_date_map[item_info["production_item"]] = schedule_date

    return results


@frappe.whitelist()
def calculate_fg_date_from_subassembly(
    production_plan: str,
    changed_item: str,
    new_schedule_date: str
) -> dict[str, Any]:
    """
    Reverse calculation: When a subcontract item's schedule_date changes,
    calculate what the FG's planned_start_date should be.

    Logic: FG_planned_start_date = schedule_date + total_lead_time_to_FG

    Args:
        production_plan: Production Plan document name
        changed_item: The production_item that was changed
        new_schedule_date: The new schedule_date set by user

    Returns:
        Dictionary with suggested FG dates
    """
    doc = frappe.get_doc("Production Plan", production_plan)

    if not doc.get("sub_assembly_items"):
        return {}

    # Find the changed row and trace back to FG
    changed_row = None
    for row in doc.sub_assembly_items:
        if row.production_item == changed_item:
            changed_row = row
            break

    if not changed_row or changed_row.type_of_manufacturing != "Subcontract":
        return {}

    # Get the lead time for the changed item
    lead_time = _get_supplier_lead_time(
        changed_row.production_item,
        changed_row.supplier,
        doc.company
    ) if changed_row.supplier else 0

    # Build parent chain to find FG and calculate total lead time
    # We need to traverse up from changed_item to FG, summing lead times
    parent_chain = _build_parent_chain(doc, changed_item)

    # Calculate the new FG date by working forward from the schedule_date
    new_date = getdate(new_schedule_date)

    # Add the changed item's lead time first
    new_fg_date = add_days(new_date, lead_time)

    # Then add lead times of all parent subcontract items
    for parent_info in parent_chain:
        if parent_info["type"] == "Subcontract":
            new_fg_date = add_days(new_fg_date, parent_info["lead_time"])

    # Find which FG item this belongs to
    fg_item = parent_chain[-1]["item"] if parent_chain else changed_row.parent_item_code

    return {
        "fg_item": fg_item,
        "suggested_planned_start_date": str(_to_datetime(new_fg_date)),
    }


def _build_parent_chain(doc: Document, item_code: str) -> list[dict[str, Any]]:
    """
    Build the chain of parents from an item up to the FG item.

    Returns list of dicts with item, type_of_manufacturing, and lead_time.
    """
    # Build lookup maps
    item_to_row = {row.production_item: row for row in doc.sub_assembly_items}
    fg_items = {po.item_code for po in doc.get("po_items") or []}

    chain = []
    current_item = item_code

    while current_item in item_to_row:
        row = item_to_row[current_item]
        parent = row.parent_item_code

        if parent in fg_items:
            # Parent is FG item, we're done
            chain.append({
                "item": parent,
                "type": "FG",
                "lead_time": 0,
            })
            break
        elif parent in item_to_row:
            # Parent is another sub-assembly
            parent_row = item_to_row[parent]
            lead_time = 0
            if parent_row.type_of_manufacturing == "Subcontract" and parent_row.supplier:
                lead_time = _get_supplier_lead_time(
                    parent_row.production_item,
                    parent_row.supplier,
                    doc.company
                )
            chain.append({
                "item": parent,
                "type": parent_row.type_of_manufacturing,
                "lead_time": lead_time,
            })
            current_item = parent
        else:
            # Parent not found, assume it's FG
            chain.append({
                "item": parent,
                "type": "FG",
                "lead_time": 0,
            })
            break

    return chain


def _batch_fetch_delivery_dates(doc: Document, combine_items: bool) -> dict[str, Any]:
    """
    Batch fetch all delivery dates.

    Performance: 1-2 queries total regardless of number of items.

    Args:
        doc: Production Plan document
        combine_items: Whether items are combined by BOM

    Returns:
        Delivery date cache dict
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

    return delivery_cache


def _batch_fetch_bom_operations(doc: Document) -> dict[str, list[dict[str, Any]]]:
    """
    Batch fetch all BOM operations for items in the production plan.

    Args:
        doc: Production Plan document

    Returns:
        Dict mapping BOM name to list of operations with time_in_mins and custom_batchsize
    """
    po_items_list = list(doc.get("po_items") or [])
    bom_nos = list(set([pi.bom_no for pi in po_items_list if pi.bom_no]))

    if not bom_nos:
        return {}

    # Fetch all operations for these BOMs in one query
    operations_data = frappe.db.sql(
        """
        SELECT
            parent as bom_no,
            time_in_mins,
            custom_batchsize,
            operation,
            idx
        FROM `tabBOM Operation`
        WHERE parent IN %(bom_nos)s
        ORDER BY parent, idx
    """,
        {"bom_nos": bom_nos},
        as_dict=True,
    )

    # Group by BOM
    bom_operations: dict[str, list[dict[str, Any]]] = {}
    for op in operations_data:
        if op.bom_no not in bom_operations:
            bom_operations[op.bom_no] = []
        bom_operations[op.bom_no].append(op)

    return bom_operations


def _calculate_production_minutes(
    bom_no: str,
    planned_qty: float,
    bom_time_cache: dict[str, list[dict[str, Any]]]
) -> float:
    """
    Calculate production time in minutes based on BOM operations.

    Formula for each operation:
    - time_per_unit = time_in_mins / custom_batchsize
    - total_time_for_operation = time_per_unit × planned_qty
    - Sum all operations

    Args:
        bom_no: BOM number
        planned_qty: Planned quantity to produce
        bom_time_cache: Cache of BOM operations

    Returns:
        Production time in minutes
    """
    if not bom_no or bom_no not in bom_time_cache:
        return 0.0

    operations = bom_time_cache[bom_no]
    if not operations:
        return 0.0

    total_minutes = 0.0

    for op in operations:
        time_in_mins = float(op.get("time_in_mins") or 0)
        custom_batchsize = float(op.get("custom_batchsize") or 1)

        if custom_batchsize <= 0:
            custom_batchsize = 1  # Avoid division by zero

        # Calculate time per unit
        time_per_unit = time_in_mins / custom_batchsize

        # Calculate total time for this operation
        operation_total_time = time_per_unit * planned_qty

        total_minutes += operation_total_time

    return total_minutes


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


def _subtract_minutes_from_datetime(dt: Any, minutes: float) -> datetime:
    """
    Subtract minutes from a datetime.

    Args:
        dt: Datetime object or string
        minutes: Minutes to subtract

    Returns:
        Datetime object with minutes subtracted
    """
    if not dt:
        return now_datetime()

    dt_obj = get_datetime(dt)
    return dt_obj - timedelta(minutes=minutes)


def set_subcontracting_suppliers(doc: Document, method: str | None = None) -> None:
    """
    Auto-populate suppliers, warehouses, and calculate schedule_date for sub-assembly items.

    For all items:
    - Auto-populates fg_warehouse from Item Default table (if defined)

    For Subcontract items:
    - Uses Item Subcontracting Supplier table to find default supplier
    - Calculates schedule_date based on supplier lead time

    For In House items:
    - Calculates schedule_date based on BOM operations time
    - Uses same logic as FG items: time_per_unit = time_in_mins / custom_batchsize

    Calculates schedule_date by working backwards from FG's planned_start_date:
    - Direct children of FG: schedule_date = FG.planned_start_date - production_time
    - Nested children: schedule_date = parent's_schedule_date - production_time

    Args:
        doc: Production Plan document
        method: Hook method name (unused)
    """
    del method  # Unused but required for hook signature

    # Skip all date logic during import or when user dates were manually preserved
    if frappe.flags.in_import or doc.get("custom_skip_date_calculation"):
        return

    if not doc.get("sub_assembly_items"):
        return

    # If SFG dates were manually changed, skip recalculating them
    # The manual changes (and cascade updates) should be preserved
    if getattr(doc, 'custom_sfg_dates_manually_changed', 0):
        # Still populate warehouses for new items
        for row in doc.sub_assembly_items:
            if not row.fg_warehouse and row.production_item:
                warehouse = frappe.db.get_value(
                    "Item Default",
                    {"parent": row.production_item, "company": doc.company},
                    "default_warehouse"
                )
                if warehouse:
                    row.fg_warehouse = warehouse

        # Clear the flag after processing
        doc.custom_sfg_dates_manually_changed = 0
        return

    # Build FG item -> planned_start_date map from po_items
    fg_dates: dict[str, Any] = {}
    for po_item in doc.get("po_items") or []:
        if po_item.item_code and po_item.planned_start_date:
            fg_dates[po_item.item_code] = po_item.planned_start_date

    # Collect ALL subcontract items for supplier/lead_time lookup
    subcontract_items: list[str] = [
        d.production_item
        for d in doc.sub_assembly_items
        if d.type_of_manufacturing == "Subcontract"
    ]

    # Batch fetch default suppliers and lead times for subcontract items
    supplier_map: dict[str, Any] = {}
    if subcontract_items:
        suppliers_data = frappe.db.sql(
            """
            SELECT
                parent as item_code,
                supplier,
                lead_time_days
            FROM `tabItem Subcontracting Supplier`
            WHERE parent IN %(items)s
              AND company = %(company)s
              AND is_default = 1
        """,
            {"items": subcontract_items, "company": doc.company},
            as_dict=True,
        )
        supplier_map = {s.item_code: s for s in suppliers_data}

    # Batch fetch default warehouses for ALL sub-assembly items (from Item Defaults)
    all_production_items: list[str] = [
        d.production_item for d in doc.sub_assembly_items if d.production_item
    ]
    warehouse_map: dict[str, str] = {}
    if all_production_items:
        warehouse_data = frappe.db.sql(
            """
            SELECT
                parent as item_code,
                default_warehouse
            FROM `tabItem Default`
            WHERE parent IN %(items)s
              AND company = %(company)s
              AND default_warehouse IS NOT NULL
              AND default_warehouse != ''
        """,
            {"items": all_production_items, "company": doc.company},
            as_dict=True,
        )
        warehouse_map = {w.item_code: w.default_warehouse for w in warehouse_data}

    # Batch fetch BOM operations for ALL sub-assembly items (both In House and Subcontract)
    bom_time_cache = _batch_fetch_subassembly_bom_operations(doc)

    # ========== CASCADING WITH BACKWARD PROPAGATION ==========
    # Multi-pass approach:
    # 1. Calculate initial dates
    # 2. Adjust backdated items
    # 3. Propagate constraints backward: if child extends, parent must wait

    allow_backdated = _get_allow_backdated_setting()
    today = getdate()
    today_datetime = _to_datetime(today)

    # Store row metadata with parent/child relationships
    row_data_list: list[dict[str, Any]] = []
    production_item_to_data: dict[str, dict[str, Any]] = {}

    # PASS 1: Collect metadata and calculate initial dates
    for row in doc.sub_assembly_items:
        # Auto-populate fg_warehouse
        if not row.fg_warehouse and row.production_item in warehouse_map:
            row.fg_warehouse = warehouse_map[row.production_item]

        # Get time value based on type
        if row.type_of_manufacturing == "Subcontract":
            supplier_info = supplier_map.get(row.production_item)
            if not row.supplier and supplier_info:
                row.supplier = supplier_info.supplier

            lead_time = 0
            if supplier_info:
                lead_time = int(supplier_info.lead_time_days or 0)
            elif row.supplier:
                lead_time = _get_supplier_lead_time(row.production_item, row.supplier, doc.company)

            time_value = lead_time
            time_type = "lead_time"
        else:
            time_value = _calculate_production_minutes(row.bom_no, row.qty, bom_time_cache)
            time_type = "production_minutes"

        data = {
            "row": row,
            "parent_item": row.parent_item_code,
            "production_item": row.production_item,
            "time_value": time_value,
            "time_type": time_type,
            "schedule_date": None,
            "end_date": None,
            "was_adjusted": False
        }
        row_data_list.append(data)
        production_item_to_data[row.production_item] = data

    # PASS 2: Calculate dates with forward cascade
    for data in row_data_list:
        parent_item = data["parent_item"]

        # Get base_date (when parent needs this item)
        if parent_item in fg_dates:
            base_date = get_datetime(fg_dates[parent_item])
        elif parent_item in production_item_to_data:
            base_date = production_item_to_data[parent_item]["schedule_date"]
        else:
            base_date = get_datetime(data["row"].schedule_date) if data["row"].schedule_date else now_datetime()

        # Calculate schedule_date
        if data["time_type"] == "lead_time":
            if data["time_value"] > 0:
                calculated_schedule = add_days(getdate(base_date), -data["time_value"])
            else:
                calculated_schedule = getdate(base_date)
        else:
            if data["time_value"] > 0:
                calculated_schedule = getdate(_subtract_minutes_from_datetime(base_date, data["time_value"]))
            else:
                calculated_schedule = getdate(base_date)

        # Check if backdated and adjust
        if not allow_backdated and calculated_schedule < today:
            data["schedule_date"] = today_datetime

            if data["time_type"] == "lead_time":
                data["end_date"] = _to_datetime(add_days(today, data["time_value"]))
            else:
                prod_days = data["time_value"] / (60 * 24)
                data["end_date"] = _to_datetime(add_days(today, math.ceil(prod_days)))

            data["was_adjusted"] = True
        else:
            if data["time_type"] == "lead_time":
                data["schedule_date"] = _to_datetime(calculated_schedule)
            else:
                data["schedule_date"] = _subtract_minutes_from_datetime(base_date, data["time_value"])
            data["end_date"] = base_date

    # PASS 3: Backward propagation (if child extends, parent waits)
    max_iterations = 10
    for iteration in range(max_iterations):
        changes_made = False

        for data in row_data_list:
            parent_item = data["parent_item"]

            # Skip if parent is FG
            if parent_item in fg_dates:
                continue

            # Check if parent exists
            if parent_item not in production_item_to_data:
                continue

            parent_data = production_item_to_data[parent_item]

            # If child's end_date > parent's schedule_date, parent must wait
            if getdate(data["end_date"]) > getdate(parent_data["schedule_date"]):
                parent_data["schedule_date"] = data["end_date"]

                # Recalculate parent's end_date
                if parent_data["time_type"] == "lead_time":
                    parent_data["end_date"] = _to_datetime(add_days(getdate(data["end_date"]), parent_data["time_value"]))
                else:
                    prod_days = parent_data["time_value"] / (60 * 24)
                    parent_data["end_date"] = _to_datetime(add_days(getdate(data["end_date"]), math.ceil(prod_days)))

                parent_data["was_adjusted"] = True
                changes_made = True

        if not changes_made:
            break

    # PASS 4: Apply final dates and collect adjustments
    adjustments_made: list[dict[str, Any]] = []

    for data in row_data_list:
        data["row"].schedule_date = data["schedule_date"]
        data["row"].custom_schedule_end_date = data["end_date"]

        if data["was_adjusted"]:
            if data["time_type"] == "lead_time":
                time_str = f"{data['time_value']} days"
            else:
                prod_days = data["time_value"] / (60 * 24)
                time_str = f"{prod_days:.1f} days"

            adjustments_made.append({
                "idx": data["row"].idx,
                "item": data["production_item"],
                "type": data["row"].type_of_manufacturing,
                "time": time_str,
                "schedule": getdate(data["schedule_date"]),
                "end": getdate(data["end_date"])
            })

    # Show consolidated message
    if adjustments_made:
        max_end_date = max(adj["end"] for adj in adjustments_made)

        details = "<br>".join([
            f"Row #{adj['idx']} ({adj['item']}): {adj['type']}, {adj['time']}, Schedule={frappe.format(adj['schedule'], 'Date')}, End={frappe.format(adj['end'], 'Date')}"
            for adj in adjustments_made
        ])

        frappe.msgprint(
            msg=_(
                "Sub Assembly items adjusted due to backdating constraints:<br><br>"
                "{0}<br><br>"
                "⚠️ Latest item ready by <b>{1}</b>."
            ).format(details, frappe.format(max_end_date, "Date")),
            title=_("Sub Assembly Schedule Adjusted"),
            indicator="orange"
        )


def adjust_mr_items_and_propagate(doc: Document, method: str | None = None) -> None:
    """
    Smart backdating adjustment for mr_items + upstream propagation.

    1. If custom_start_date < today: shift to today, schedule_date = today + lead_time
    2. Propagate RM delays up the chain:
       - Multi-level BOM (SFGs exist): RM → SFG → FG
       - Single-level BOM (no SFGs):   RM → FG
    """
    del method  # Unused but required for hook signature

    # Skip all date logic during import or when user dates were manually preserved
    if frappe.flags.in_import or doc.get("custom_skip_date_calculation"):
        return

    if _get_allow_backdated_setting():
        return

    today = getdate()
    mr_adjustments: list[dict[str, Any]] = []

    # --- Step 1: Adjust backdated mr_items ---
    for row in doc.get("mr_items") or []:
        if not row.get("custom_start_date"):
            continue

        start_date = getdate(row.custom_start_date)
        if start_date >= today:
            continue

        # Fetch lead_time from Item Subcontracting Supplier
        lead_time = 0
        if row.get("custom_supplier"):
            lead_time_result = frappe.db.get_value(
                "Item Subcontracting Supplier",
                {"parent": row.item_code, "supplier": row.custom_supplier, "company": doc.company},
                "lead_time_days"
            )
            lead_time = int(lead_time_result or 0)

        original_schedule_date = getdate(row.schedule_date) if row.get("schedule_date") else today
        new_schedule_date = add_days(today, lead_time)

        row.custom_start_date = _to_datetime(today)
        row.schedule_date = _to_datetime(new_schedule_date)

        mr_adjustments.append({
            "idx": row.idx,
            "item_code": row.item_code,
            "lead_time": lead_time,
            "original_start": start_date,
            "original_schedule": original_schedule_date,
            "new_start": today,
            "new_schedule": new_schedule_date,
        })

    # --- Step 2: Show consolidated MR adjustment message (only if adjustments made this save) ---
    if mr_adjustments:
        max_mr_schedule = max(a["new_schedule"] for a in mr_adjustments)
        details = "<br>".join([
            "Row #{0} <b>{1}</b> — Start: <b>{2}</b> → <b>{3}</b> | Schedule: <b>{4}</b> → <b>{5}</b> (lead time: {6}d)".format(
                a["idx"],
                a["item_code"],
                frappe.format(a["original_start"], "Date"),
                frappe.format(a["new_start"], "Date"),
                frappe.format(a["original_schedule"], "Date"),
                frappe.format(a["new_schedule"], "Date"),
                a["lead_time"],
            )
            for a in mr_adjustments
        ])

        frappe.msgprint(
            msg=_(
                "Material Request items adjusted due to backdating constraints:<br><br>"
                "{0}<br><br>"
                "⚠️ Latest material needed by <b>{1}</b>."
            ).format(details, frappe.format(max_mr_schedule, "Date")),
            title=_("Material Request Schedule Adjusted"),
            indicator="orange"
        )

    # --- Step 3: Propagate RM delays using current schedule_dates ---
    # (Catches both fresh adjustments and previously adjusted but not yet propagated dates)
    if doc.get("mr_items"):
        all_rm_schedules: dict[str, Any] = {
            row.item_code: getdate(row.schedule_date)
            for row in doc.mr_items
            if row.get("schedule_date")
        }
        if doc.get("sub_assembly_items"):
            _propagate_rm_delays_to_sfg_and_fg(doc, all_rm_schedules)
        else:
            _propagate_rm_delays_to_fg(doc, all_rm_schedules)

    # --- Step 4: Enforce FG planned_start >= all top-level SFG end dates ---
    # Runs always when SFGs exist — catches both RM propagation and manual SFG changes
    if doc.get("sub_assembly_items"):
        _enforce_fg_waits_for_sfg(doc)


def _propagate_rm_delays_to_sfg_and_fg(doc: Document, adjusted_rm_schedules: dict[str, Any]) -> None:
    """
    Multi-level BOM: RM schedule_date delay → push SFG dates → push FG planned_start_date.

    Uses duration (end - schedule) already set on SFG rows to preserve production/lead times.
    Backward propagation among SFGs: if child end > parent schedule, parent waits.
    """
    # Collect all SFG bom_nos
    sfg_bom_nos = list(set(row.bom_no for row in doc.sub_assembly_items if row.bom_no))
    if not sfg_bom_nos:
        return

    # Query: which SFG BOMs contain the adjusted raw materials
    bom_item_links = frappe.db.sql(
        """
        SELECT parent as bom_no, item_code
        FROM `tabBOM Item`
        WHERE parent IN %(bom_nos)s
          AND item_code IN %(items)s
        """,
        {"bom_nos": sfg_bom_nos, "items": list(adjusted_rm_schedules.keys())},
        as_dict=True,
    )

    if not bom_item_links:
        return

    # bom_no → max delayed RM schedule_date
    bom_to_max_rm_schedule: dict[str, Any] = {}
    for link in bom_item_links:
        rm_sched = adjusted_rm_schedules[link.item_code]
        if link.bom_no not in bom_to_max_rm_schedule or rm_sched > bom_to_max_rm_schedule[link.bom_no]:
            bom_to_max_rm_schedule[link.bom_no] = rm_sched

    if not bom_to_max_rm_schedule:
        return

    # Build SFG map: production_item → working data
    sfg_map: dict[str, dict[str, Any]] = {}
    for row in doc.sub_assembly_items:
        if not row.schedule_date or not row.custom_schedule_end_date:
            continue
        schedule = getdate(row.schedule_date)
        end = getdate(row.custom_schedule_end_date)
        sfg_map[row.production_item] = {
            "row": row,
            "schedule_date": schedule,
            "end_date": end,
            "duration_days": max((end - schedule).days, 0),
            "parent_item_code": row.parent_item_code,
            "bom_no": row.bom_no,
            "original_schedule": schedule,
            "original_end": end,
        }

    # Step A: Push SFG schedule forward where RM is delayed
    sfg_changed = False
    for item, data in sfg_map.items():
        if data["bom_no"] not in bom_to_max_rm_schedule:
            continue
        rm_max = bom_to_max_rm_schedule[data["bom_no"]]
        if rm_max > data["schedule_date"]:
            data["schedule_date"] = rm_max
            data["end_date"] = add_days(rm_max, data["duration_days"])
            sfg_changed = True

    if not sfg_changed:
        return

    # Step B: Backward propagation — if child end > parent schedule, parent waits
    for _iter in range(10):
        changes_made = False
        for item, data in sfg_map.items():
            parent = data["parent_item_code"]
            if parent not in sfg_map:
                continue
            parent_data = sfg_map[parent]
            if data["end_date"] > parent_data["schedule_date"]:
                parent_data["schedule_date"] = data["end_date"]
                parent_data["end_date"] = add_days(data["end_date"], parent_data["duration_days"])
                changes_made = True
        if not changes_made:
            break

    # Step C: Apply updated dates to SFG rows + collect changes
    sfg_adjustments: list[dict[str, Any]] = []
    for item, data in sfg_map.items():
        if data["schedule_date"] != data["original_schedule"] or data["end_date"] != data["original_end"]:
            data["row"].schedule_date = _to_datetime(data["schedule_date"])
            data["row"].custom_schedule_end_date = _to_datetime(data["end_date"])
            sfg_adjustments.append({
                "production_item": item,
                "original_schedule": data["original_schedule"],
                "new_schedule": data["schedule_date"],
                "original_end": data["original_end"],
                "new_end": data["end_date"],
            })

    # Show SFG propagation message (FG update handled by _enforce_fg_waits_for_sfg)
    if sfg_adjustments:
        sfg_details = "<br>".join([
            "<b>{0}</b> — Schedule: {1} → <b>{2}</b> | End: {3} → <b>{4}</b>".format(
                a["production_item"],
                frappe.format(a["original_schedule"], "Date"),
                frappe.format(a["new_schedule"], "Date"),
                frappe.format(a["original_end"], "Date"),
                frappe.format(a["new_end"], "Date"),
            )
            for a in sfg_adjustments
        ])

        frappe.msgprint(
            msg=_("Sub Assembly items rescheduled due to raw material delay:<br><br>{0}").format(sfg_details),
            title=_("Sub Assembly Schedule Adjusted"),
            indicator="orange"
        )


def _propagate_rm_delays_to_fg(doc: Document, adjusted_rm_schedules: dict[str, Any]) -> None:
    """
    Single-level BOM: RM schedule_date delay → push FG planned_start_date directly.
    """
    fg_bom_nos = list(set(row.bom_no for row in doc.po_items if row.get("bom_no")))
    if not fg_bom_nos:
        return

    # Query: which FG BOMs contain the adjusted raw materials
    bom_item_links = frappe.db.sql(
        """
        SELECT parent as bom_no, item_code
        FROM `tabBOM Item`
        WHERE parent IN %(bom_nos)s
          AND item_code IN %(items)s
        """,
        {"bom_nos": fg_bom_nos, "items": list(adjusted_rm_schedules.keys())},
        as_dict=True,
    )

    if not bom_item_links:
        return

    # bom_no → max delayed RM schedule_date
    bom_to_max_rm_schedule: dict[str, Any] = {}
    for link in bom_item_links:
        rm_sched = adjusted_rm_schedules[link.item_code]
        if link.bom_no not in bom_to_max_rm_schedule or rm_sched > bom_to_max_rm_schedule[link.bom_no]:
            bom_to_max_rm_schedule[link.bom_no] = rm_sched

    # Update FG planned_start_date where RM delay exceeds it
    fg_adjustments: list[dict[str, Any]] = []
    for po_item in doc.po_items:
        if not po_item.get("bom_no") or po_item.bom_no not in bom_to_max_rm_schedule:
            continue
        max_rm = bom_to_max_rm_schedule[po_item.bom_no]
        if max_rm > getdate(po_item.planned_start_date):
            fg_adjustments.append({
                "item_code": po_item.item_code,
                "original": getdate(po_item.planned_start_date),
                "new": max_rm,
            })
            po_item.planned_start_date = _to_datetime(max_rm)

    if fg_adjustments:
        fg_details = "<br>".join([
            "<b>{0}</b> — Planned Start: {1} → <b>{2}</b>".format(
                a["item_code"],
                frappe.format(a["original"], "Date"),
                frappe.format(a["new"], "Date"),
            )
            for a in fg_adjustments
        ])
        frappe.msgprint(
            msg=_(
                "FG items rescheduled due to raw material delay:<br><br>{0}"
            ).format(fg_details),
            title=_("FG Schedule Adjusted"),
            indicator="orange"
        )


def _enforce_fg_waits_for_sfg(doc: Document) -> None:
    """
    Constraint: FG planned_start_date must be >= all top-level SFG custom_schedule_end_dates.

    Runs after SFG dates are finalized (whether by set_subcontracting_suppliers,
    RM propagation, or manual user change). If any top-level SFG ends after FG starts,
    push FG forward to that SFG's end date.
    """
    fg_item_codes = {row.item_code for row in (doc.get("po_items") or [])}
    fg_adjustments: list[dict[str, Any]] = []

    # Find max end_date per FG from its direct SFG children
    fg_max_end: dict[str, Any] = {}
    for row in doc.sub_assembly_items:
        if row.parent_item_code not in fg_item_codes or not row.custom_schedule_end_date:
            continue
        sfg_end = getdate(row.custom_schedule_end_date)
        if row.parent_item_code not in fg_max_end or sfg_end > fg_max_end[row.parent_item_code]:
            fg_max_end[row.parent_item_code] = sfg_end

    # Push FG where needed
    for po_item in doc.po_items:
        if po_item.item_code not in fg_max_end:
            continue
        max_sfg_end = fg_max_end[po_item.item_code]
        if max_sfg_end > getdate(po_item.planned_start_date):
            fg_adjustments.append({
                "item_code": po_item.item_code,
                "original": getdate(po_item.planned_start_date),
                "new": max_sfg_end,
            })
            po_item.planned_start_date = _to_datetime(max_sfg_end)

    if fg_adjustments:
        fg_details = "<br>".join([
            "<b>{0}</b> — Planned Start: {1} → <b>{2}</b>".format(
                a["item_code"],
                frappe.format(a["original"], "Date"),
                frappe.format(a["new"], "Date"),
            )
            for a in fg_adjustments
        ])
        frappe.msgprint(
            msg=_(
                "FG planned start date updated — waiting for Sub Assembly:<br><br>{0}"
            ).format(fg_details),
            title=_("FG Schedule Adjusted"),
            indicator="orange"
        )


def _batch_fetch_subassembly_bom_operations(doc: Document) -> dict[str, list[dict[str, Any]]]:
    """
    Batch fetch all BOM operations for sub-assembly items in the production plan.

    Args:
        doc: Production Plan document

    Returns:
        Dict mapping BOM name to list of operations with time_in_mins and custom_batchsize
    """
    if not doc.get("sub_assembly_items"):
        return {}

    sub_assembly_list = list(doc.get("sub_assembly_items") or [])
    bom_nos = list(set([item.bom_no for item in sub_assembly_list if item.bom_no]))

    if not bom_nos:
        return {}

    # Fetch all operations for these BOMs in one query
    operations_data = frappe.db.sql(
        """
        SELECT
            parent as bom_no,
            time_in_mins,
            custom_batchsize,
            operation,
            idx
        FROM `tabBOM Operation`
        WHERE parent IN %(bom_nos)s
        ORDER BY parent, idx
    """,
        {"bom_nos": bom_nos},
        as_dict=True,
    )

    # Group by BOM
    bom_operations: dict[str, list[dict[str, Any]]] = {}
    for op in operations_data:
        if op.bom_no not in bom_operations:
            bom_operations[op.bom_no] = []
        bom_operations[op.bom_no].append(op)

    return bom_operations


def _get_supplier_lead_time(item_code: str, supplier: str, company: str) -> int:
    """
    Get lead time for a specific supplier from Item Subcontracting Supplier table.

    Args:
        item_code: Item code
        supplier: Supplier name
        company: Company name

    Returns:
        Lead time in days, or 0 if not found
    """
    result = frappe.db.get_value(
        "Item Subcontracting Supplier",
        {"parent": item_code, "supplier": supplier, "company": company},
        "lead_time_days",
    )
    return int(result or 0)


@frappe.whitelist()
def calculate_fg_dates_from_subassembly(
    production_plan_name: str,
    subassembly_data: list[dict[str, Any]] | str,
    original_dates: dict[str, dict[str, Any]] | str | None = None
) -> list[dict[str, Any]]:
    """
    Calculate FG planned_start_date changes based on deltas from original sub-assembly dates.

    The key insight: We compare current sub-assembly dates against original dates to detect
    what the user actually changed. Then we propagate only those deltas up the hierarchy.

    This handles multi-level BOMs correctly:
    - Changing a child node affects its parent(s) and the FG
    - Changes don't affect sibling sub-assemblies (other branches of the BOM tree)

    Logic:
    1. Load original dates from __onload (stored when "Get Sub Assembly Items" was clicked)
    2. Compare current vs original to find which items changed and by how much
    3. For each changed item, trace up the hierarchy to its FG
    4. Apply the delta to the FG's planned_start_date
    5. If multiple sub-assemblies of the same FG changed, use the largest adjustment

    Args:
        production_plan_name: Name of the Production Plan
        subassembly_data: List of dicts with name, production_item, parent_item_code,
                         schedule_date, type_of_manufacturing
        original_dates: Dict mapping row.name to original date info from __onload

    Returns:
        List of dicts with fg_item, current_date, new_date for items that need updates
    """
    import json

    if isinstance(subassembly_data, str):
        subassembly_data = json.loads(subassembly_data)

    if isinstance(original_dates, str):
        original_dates = json.loads(original_dates)

    if not original_dates:
        original_dates = {}

    # Get the Production Plan document
    doc = frappe.get_doc("Production Plan", production_plan_name)

    # Get FG items from po_items
    po_items_list: list[Any] = list(doc.get("po_items") or [])
    fg_items = {po_item.item_code for po_item in po_items_list}

    # Build parent-child map for hierarchy traversal
    parent_map: dict[str, str] = {}  # production_item -> parent_item_code

    for item_info in subassembly_data:
        prod_item = item_info.get("production_item")
        parent = item_info.get("parent_item_code")
        if prod_item and parent:
            parent_map[prod_item] = parent

    # Detect changes: Compare current dates vs original dates
    # Store deltas in minutes (positive = moved later, negative = moved earlier)
    changed_items: dict[str, dict[str, Any]] = {}

    # Build a fallback lookup by production_item for when row names don't match
    # (e.g., when "Get Sub Assembly Items" regenerates rows after doc was loaded)
    original_by_production_item: dict[str, dict[str, Any]] = {}
    for row_name, info in original_dates.items():
        prod_item = info.get("production_item")
        if prod_item:
            original_by_production_item[prod_item] = info

    for item_info in subassembly_data:
        row_name = item_info.get("name")
        prod_item = item_info.get("production_item")
        current_date_str = item_info.get("schedule_date")
        current_end_date_str = item_info.get("custom_schedule_end_date")

        if not prod_item or not current_date_str:
            continue

        # Check if we have original date for this row (by name first, then by production_item)
        original_info = None
        if row_name and row_name in original_dates:
            original_info = original_dates[row_name]
        elif prod_item in original_by_production_item:
            # Fallback: match by production_item when row names don't match
            original_info = original_by_production_item[prod_item]

        if not original_info:
            # No original date - skip
            continue

        original_date_str = original_info.get("schedule_date")
        original_end_date_str = original_info.get("custom_schedule_end_date")

        if not original_date_str:
            continue

        # Compare schedule_date
        current_date = get_datetime(current_date_str)
        original_date = get_datetime(original_date_str)
        delta_seconds = (current_date - original_date).total_seconds()

        # Also compare custom_schedule_end_date if available
        end_date_delta_seconds = 0.0
        if current_end_date_str and original_end_date_str:
            current_end_date = get_datetime(current_end_date_str)
            original_end_date = get_datetime(original_end_date_str)
            end_date_delta_seconds = (current_end_date - original_end_date).total_seconds()

        # Use the larger delta (either schedule_date or custom_schedule_end_date changed)
        effective_delta_seconds = delta_seconds
        if abs(end_date_delta_seconds) > abs(delta_seconds):
            effective_delta_seconds = end_date_delta_seconds

        # Only consider significant changes (> 60 seconds)
        if abs(effective_delta_seconds) > 60:
            changed_items[prod_item] = {
                "delta_minutes": effective_delta_seconds / 60.0,
                "parent_item_code": item_info.get("parent_item_code")
            }

    # If nothing changed, return empty list
    if not changed_items:
        return []

    # For each changed item, trace up to FG and apply delta
    fg_adjustments: dict[str, float] = {}  # fg_item -> delta_minutes (largest adjustment needed)

    for prod_item, change_info in changed_items.items():
        delta_minutes = change_info["delta_minutes"]

        # Trace this item back to its FG
        current = prod_item
        path_to_fg = [current]

        # Build path from sub-assembly up to FG
        while current and current not in fg_items:
            if current in parent_map:
                current = parent_map[current]
                path_to_fg.append(current)
            else:
                break

        # Check if we reached an FG
        if not path_to_fg or path_to_fg[-1] not in fg_items:
            continue

        fg_item = path_to_fg[-1]

        # Apply delta to FG
        # If this sub-assembly moved later (+delta), FG must also move later
        # If this sub-assembly moved earlier (-delta), FG can move earlier
        if fg_item not in fg_adjustments:
            fg_adjustments[fg_item] = delta_minutes
        else:
            # Multiple sub-assemblies changed for this FG
            # Use the largest positive adjustment (latest date wins)
            if delta_minutes > fg_adjustments[fg_item]:
                fg_adjustments[fg_item] = delta_minutes

    # Build impacts list
    impacts = []
    for po_item in po_items_list:
        fg_item = po_item.item_code

        if fg_item not in fg_adjustments:
            # No changes for this FG
            continue

        current_planned_start = po_item.planned_start_date
        if not current_planned_start:
            # FG has no planned start date - skip
            continue

        # Apply the delta
        delta_minutes = fg_adjustments[fg_item]
        new_planned_start = get_datetime(current_planned_start) + timedelta(minutes=delta_minutes)

        # Check if the change is significant
        time_diff_seconds = abs(delta_minutes * 60)
        if time_diff_seconds > 60:
            impacts.append({
                "fg_item": fg_item,
                "current_date": str(current_planned_start),
                "new_date": str(new_planned_start)
            })

    return impacts


@frappe.whitelist()
def get_subcontract_lead_time(
    item_code: str,
    supplier: str | None = None,
    company: str | None = None
) -> int:
    """
    Get lead time for a subcontract item.

    Args:
        item_code: Item code
        supplier: Supplier name (optional)
        company: Company name (optional)

    Returns:
        Lead time in days
    """
    if not item_code:
        return 0

    # If supplier is provided, get lead time for that specific supplier
    if supplier and company:
        result = frappe.db.get_value(
            "Item Subcontracting Supplier",
            {"parent": item_code, "supplier": supplier, "company": company},
            "lead_time_days",
        )
        if result:
            return int(result)

    # Otherwise, get lead time from default supplier
    if company:
        result = frappe.db.get_value(
            "Item Subcontracting Supplier",
            {"parent": item_code, "company": company, "is_default": 1},
            "lead_time_days",
        )
        if result:
            return int(result)

    return 0


@frappe.whitelist()
def get_production_time(bom_no: str, qty: float | str) -> float:
    """
    Get production time in minutes for a BOM based on its operations.

    Args:
        bom_no: BOM number
        qty: Quantity to produce

    Returns:
        Production time in minutes
    """
    if not bom_no:
        return 0.0

    qty = float(qty) if qty else 0.0
    if qty <= 0:
        return 0.0

    # Fetch BOM operations
    operations = frappe.db.sql(
        """
        SELECT time_in_mins, custom_batchsize
        FROM `tabBOM Operation`
        WHERE parent = %s
        ORDER BY idx
    """,
        (bom_no,),
        as_dict=True,
    )

    if not operations:
        return 0.0

    total_minutes = 0.0

    for op in operations:
        time_in_mins = float(op.get("time_in_mins") or 0)
        custom_batchsize = float(op.get("custom_batchsize") or 1)

        if custom_batchsize <= 0:
            custom_batchsize = 1

        # Calculate time per unit
        time_per_unit = time_in_mins / custom_batchsize

        # Calculate total time for this operation
        operation_total_time = time_per_unit * qty

        total_minutes += operation_total_time

    return total_minutes


@frappe.whitelist()
def get_item_default_warehouse(item_code: str, company: str) -> str | None:
    """
    Get default warehouse for an item from Item Default table.

    Args:
        item_code: Item code
        company: Company name

    Returns:
        Default warehouse name or None
    """
    if not item_code or not company:
        return None

    result = frappe.db.get_value(
        "Item Default",
        {"parent": item_code, "company": company},
        "default_warehouse",
    )

    return result if result else None


@frappe.whitelist()
def calculate_mr_item_dates(
    production_plan_name: str,
    mr_items_data: list[dict[str, Any]] | str
) -> dict[str, dict[str, Any]]:
    """
    Calculate schedule dates and supplier info for Material Request Plan Items.

    Logic:
    1. If SFGs exist: Find raw materials linked to SFGs, use lowest SFG schedule_date as base
    2. If NO SFGs: Find raw materials linked to FG BOMs, use FG planned_start_date as base
    3. Get the default supplier for the raw material
    4. Calculate: custom_start_date = base_date - supplier_lead_time_days
    5. Set schedule_date = base_date (when material is needed)

    Args:
        production_plan_name: Name of Production Plan
        mr_items_data: List of dicts with item_code and other MR item info

    Returns:
        Dict mapping item_code to {custom_start_date, schedule_date, custom_supplier}
    """
    import json

    if isinstance(mr_items_data, str):
        mr_items_data = json.loads(mr_items_data)

    if not mr_items_data:
        return {}

    # Get Production Plan document
    doc = frappe.get_doc("Production Plan", production_plan_name)

    # Extract all raw material item codes
    raw_material_items = [item["item_code"] for item in mr_items_data if item.get("item_code")]

    if not raw_material_items:
        return {}

    # Determine base dates: either from SFGs or from FGs (po_items)
    # raw_to_base_dates will map: raw_material -> list of base dates
    raw_to_base_dates: dict[str, list[dict[str, Any]]] = {}

    has_sfgs = bool(doc.get("sub_assembly_items"))

    if has_sfgs:
        # Case 1: SFGs exist - use SFG schedule_dates as base (original logic)
        sfg_bom_map = {}  # production_item -> {bom_no, schedule_date}
        for row in doc.sub_assembly_items:
            if row.production_item and row.bom_no and row.schedule_date:
                sfg_bom_map[row.production_item] = {
                    "bom_no": row.bom_no,
                    "schedule_date": row.schedule_date
                }

        if sfg_bom_map:
            sfg_boms = list(set([info["bom_no"] for info in sfg_bom_map.values()]))

            # Query BOM Item table to find which raw materials are in which SFG BOMs
            bom_items_data = frappe.db.sql(
                """
                SELECT parent as bom_no, item_code
                FROM `tabBOM Item`
                WHERE parent IN %(bom_nos)s
                  AND item_code IN %(raw_items)s
            """,
                {"bom_nos": sfg_boms, "raw_items": raw_material_items},
                as_dict=True,
            )

            # Build reverse mapping: bom_no -> list of raw_materials
            bom_to_raw: dict[str, list[str]] = {}
            for row in bom_items_data:
                if row.bom_no not in bom_to_raw:
                    bom_to_raw[row.bom_no] = []
                bom_to_raw[row.bom_no].append(row.item_code)

            # Build: raw_material -> list of base dates from SFGs
            for sfg_item, info in sfg_bom_map.items():
                bom_no = info["bom_no"]
                schedule_date = info["schedule_date"]

                if bom_no in bom_to_raw:
                    for raw_item in bom_to_raw[bom_no]:
                        if raw_item not in raw_to_base_dates:
                            raw_to_base_dates[raw_item] = []
                        raw_to_base_dates[raw_item].append({
                            "source_item": sfg_item,
                            "base_date": schedule_date
                        })

    # Case 2: No SFGs - use earliest FG planned_start_date for ALL MR items
    if not has_sfgs and doc.get("po_items"):
        # Get the earliest planned_start_date from all FG items
        fg_dates = []
        for row in doc.po_items:
            if row.planned_start_date:
                fg_dates.append(get_datetime(row.planned_start_date))

        if fg_dates:
            earliest_fg_date = min(fg_dates)
            # Assign this date to ALL raw materials
            for raw_item in raw_material_items:
                raw_to_base_dates[raw_item] = [{
                    "source_item": "FG",
                    "base_date": earliest_fg_date
                }]

    if not raw_to_base_dates:
        return {}

    # Batch fetch default suppliers for all raw materials
    supplier_data = frappe.db.sql(
        """
        SELECT
            parent as item_code,
            supplier,
            lead_time_days
        FROM `tabItem Subcontracting Supplier`
        WHERE parent IN %(items)s
          AND company = %(company)s
          AND is_default = 1
    """,
        {"items": raw_material_items, "company": doc.company},
        as_dict=True,
    )

    supplier_map = {s.item_code: s for s in supplier_data}

    # Calculate dates for each raw material
    results: dict[str, dict[str, Any]] = {}

    for item_code in raw_material_items:
        # Find lowest base_date from sources (SFGs or FGs) that use this raw material
        if item_code not in raw_to_base_dates:
            # This raw material is not linked to any SFG or FG BOM
            # Skip custom date calculation
            continue

        base_dates = [get_datetime(info["base_date"]) for info in raw_to_base_dates[item_code]]
        lowest_base_date = min(base_dates)

        # Get supplier info
        supplier_info = supplier_map.get(item_code)

        # Only calculate dates if supplier is defined
        if not supplier_info or not supplier_info.supplier:
            # No default supplier defined - skip this item
            continue

        lead_time = int(supplier_info.lead_time_days or 0)
        supplier_name = supplier_info.supplier

        # custom_start_date = when to order from supplier (base_date - lead_time)
        # schedule_date = when material is needed (base_date)
        if lead_time > 0:
            custom_start_date = add_days(getdate(lowest_base_date), -lead_time)
        else:
            custom_start_date = getdate(lowest_base_date)

        results[item_code] = {
            "custom_start_date": str(_to_datetime(custom_start_date)),
            "schedule_date": str(lowest_base_date),
            "custom_supplier": supplier_name
        }

    return results


@frappe.whitelist()
def get_supplier_lead_time(item_code: str, supplier: str, company: str) -> dict[str, Any]:
    """
    Get supplier lead time for a specific item and supplier combination.

    Args:
        item_code: Item code
        supplier: Supplier name
        company: Company name

    Returns:
        Dict with lead_time_days
    """
    result = frappe.db.get_value(
        "Item Subcontracting Supplier",
        {
            "parent": item_code,
            "supplier": supplier,
            "company": company,
            "is_default": 1
        },
        "lead_time_days"
    )

    return {"lead_time_days": result if result is not None else 0}


@frappe.whitelist()
def calculate_production_time_from_bom(bom_no: str) -> dict[str, Any]:
    """
    Calculate total production time in minutes from BOM operations.

    Args:
        bom_no: BOM number

    Returns:
        Dict with production_minutes
    """
    # Get BOM quantity
    bom_data = frappe.db.get_value("BOM", bom_no, ["quantity"], as_dict=True)
    if not bom_data:
        return {"production_minutes": 0}

    qty = float(bom_data.get("quantity") or 1.0)

    # Get BOM operations
    operations = frappe.db.sql(
        """
        SELECT time_in_mins, custom_batchsize
        FROM `tabBOM Operation`
        WHERE parent = %s
        ORDER BY idx
    """,
        (bom_no,),
        as_dict=True,
    )

    # Calculate total production time
    production_minutes = 0.0
    for op in operations:
        time_in_mins = float(op.get("time_in_mins") or 0)
        custom_batchsize = float(op.get("custom_batchsize") or 1)

        if custom_batchsize <= 0:
            custom_batchsize = 1

        time_per_unit = time_in_mins / custom_batchsize
        operation_time = time_per_unit * qty
        production_minutes += operation_time

    return {"production_minutes": production_minutes}


@frappe.whitelist()
def cascade_sfg_date_change(
    production_plan_name: str,
    changed_sfg_item: str,
    changed_sfg_bom: str,
    new_schedule_date: str,
    new_end_date: str | None = None,
    company: str | None = None,
    changed_sfg_idx: int | None = None
) -> dict[str, Any]:
    """
    Cascade SFG schedule_date changes to parent SFGs and child MR items.

    Args:
        production_plan_name: Production Plan name
        changed_sfg_item: The SFG item code that changed
        changed_sfg_bom: The BOM of the changed SFG
        new_schedule_date: New schedule_date value
        new_end_date: New custom_schedule_end_date value (optional)
        company: Company name
        changed_sfg_idx: The idx of the changed SFG row (only update rows with idx < this)

    Returns:
        Dict with parent_sfg_updates and mr_item_updates
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)

    if not company:
        company = doc.company

    parent_sfg_updates = []
    mr_item_updates = []

    # Convert changed_sfg_idx to int if it's a string
    if changed_sfg_idx is not None:
        changed_sfg_idx = int(changed_sfg_idx)

    # Cascade UP to parent SFGs
    if doc.get("sub_assembly_items"):
        for parent_row in doc.sub_assembly_items:
            if not parent_row.bom_no or parent_row.production_item == changed_sfg_item:
                continue

            # Only update rows ABOVE (idx < changed_sfg_idx) the changed row
            # Rows below should NOT be affected by changes above them
            if changed_sfg_idx is not None and parent_row.idx >= changed_sfg_idx:
                continue

            # Check if changed SFG is in this parent's BOM
            is_child = frappe.db.exists(
                "BOM Item",
                {"parent": parent_row.bom_no, "item_code": changed_sfg_item}
            )

            if is_child:
                # Get production time for parent
                prod_time_result = calculate_production_time_from_bom(parent_row.bom_no)
                production_mins = prod_time_result.get("production_minutes", 0)

                # Calculate new parent date
                # Parent can START when child ENDS (not child_end + production_mins!)
                # Parent ENDS after its own production time
                child_end = get_datetime(new_end_date if new_end_date else new_schedule_date)
                new_parent_start = child_end
                new_parent_end = add_to_date(child_end, minutes=production_mins)

                parent_sfg_updates.append({
                    "row_name": parent_row.name,
                    "production_item": parent_row.production_item,
                    "new_schedule_date": str(new_parent_start),
                    "new_custom_schedule_end_date": str(new_parent_end)
                })

    # Cascade DOWN to MR items
    if doc.get("mr_items"):
        # Get raw materials in changed SFG's BOM
        raw_materials = frappe.db.sql(
            """
            SELECT item_code
            FROM `tabBOM Item`
            WHERE parent = %s
        """,
            (changed_sfg_bom,),
            as_dict=True
        )

        raw_item_codes = [r.item_code for r in raw_materials]

        for mr_row in doc.mr_items:
            if mr_row.item_code in raw_item_codes and mr_row.custom_supplier:
                # Get supplier lead time
                lead_time_result = get_supplier_lead_time(
                    mr_row.item_code,
                    mr_row.custom_supplier,
                    company
                )
                lead_time = int(lead_time_result.get("lead_time_days", 0))

                # Calculate new MR dates
                new_mr_schedule_date = get_datetime(new_schedule_date)
                new_mr_custom_start_date = add_days(getdate(new_mr_schedule_date), -lead_time)

                mr_item_updates.append({
                    "row_name": mr_row.name,
                    "item_code": mr_row.item_code,
                    "new_schedule_date": str(new_mr_schedule_date),
                    "new_custom_start_date": str(_to_datetime(new_mr_custom_start_date))
                })

    return {
        "parent_sfg_updates": parent_sfg_updates,
        "mr_item_updates": mr_item_updates
    }


@frappe.whitelist()
def calculate_sfg_fg_dates_from_mr_items(
    production_plan_name: str,
    mr_items_data: list[dict[str, Any]] | str,
    original_mr_dates: dict[str, dict[str, Any]] | str | None = None
) -> dict[str, Any]:
    """
    Calculate SFG and FG date changes based on MR item custom_start_date changes.

    Logic:
    1. Compare current MR item dates vs original to detect changes
    2. For each changed MR item, find which SFGs use that raw material
    3. Calculate new SFG schedule_date = MR custom_start_date + supplier_lead_time
    4. Propagate SFG changes up to FG items

    Args:
        production_plan_name: Name of Production Plan
        mr_items_data: List of dicts with name, item_code, custom_start_date, schedule_date
        original_mr_dates: Dict mapping row.name to original date info from __onload

    Returns:
        Dict with:
        - sfg_updates: List of SFG items that need date updates
        - fg_updates: List of FG items that need date updates
    """
    import json

    if isinstance(mr_items_data, str):
        mr_items_data = json.loads(mr_items_data)

    if isinstance(original_mr_dates, str):
        original_mr_dates = json.loads(original_mr_dates)

    if not original_mr_dates:
        original_mr_dates = {}

    # Get Production Plan document
    doc = frappe.get_doc("Production Plan", production_plan_name)

    if not mr_items_data:
        return {"sfg_updates": [], "fg_updates": []}

    has_sfgs = bool(doc.get("sub_assembly_items"))

    # Detect changes in MR items
    # Compare both custom_start_date and schedule_date changes
    changed_mr_items: dict[str, dict[str, Any]] = {}

    for item_info in mr_items_data:
        row_name = item_info.get("name")
        item_code = item_info.get("item_code")
        current_start_date_str = item_info.get("custom_start_date")
        current_schedule_date_str = item_info.get("schedule_date")

        if not row_name or not item_code:
            continue

        # Check if we have original date
        if row_name not in original_mr_dates:
            continue

        original_info = original_mr_dates[row_name]
        original_start_date_str = original_info.get("custom_start_date")
        original_schedule_date_str = original_info.get("schedule_date")

        # Compare custom_start_date
        delta_seconds = 0.0
        if current_start_date_str and original_start_date_str:
            current_date = get_datetime(current_start_date_str)
            original_date = get_datetime(original_start_date_str)
            delta_seconds = (current_date - original_date).total_seconds()

        # Also compare schedule_date if custom_start_date didn't change
        schedule_delta_seconds = 0.0
        if current_schedule_date_str and original_schedule_date_str:
            current_schedule = get_datetime(current_schedule_date_str)
            original_schedule = get_datetime(original_schedule_date_str)
            schedule_delta_seconds = (current_schedule - original_schedule).total_seconds()

        # Use the larger delta
        effective_delta = delta_seconds if abs(delta_seconds) > abs(schedule_delta_seconds) else schedule_delta_seconds

        # Only consider significant changes (> 60 seconds)
        if abs(effective_delta) > 60:
            changed_mr_items[item_code] = {
                "delta_minutes": effective_delta / 60.0,
                "new_start_date": get_datetime(current_start_date_str) if current_start_date_str else get_datetime(current_schedule_date_str),
                "new_schedule_date": get_datetime(current_schedule_date_str) if current_schedule_date_str else None
            }

    if not changed_mr_items:
        return {"sfg_updates": [], "fg_updates": []}

    # Case 1: No SFGs - directly update FG dates based on MR item changes
    if not has_sfgs:
        fg_updates = []

        # Get the largest delta from all changed MR items
        max_delta_minutes = 0.0
        for item_code, change_info in changed_mr_items.items():
            if abs(change_info["delta_minutes"]) > abs(max_delta_minutes):
                max_delta_minutes = change_info["delta_minutes"]

        # Apply delta to all FG items
        if abs(max_delta_minutes) > 1 and doc.get("po_items"):  # More than 1 minute change
            for po_item in doc.po_items:
                if po_item.planned_start_date:
                    current_date = get_datetime(po_item.planned_start_date)
                    new_date = current_date + timedelta(minutes=max_delta_minutes)

                    fg_updates.append({
                        "fg_item": po_item.item_code,
                        "current_date": str(current_date),
                        "new_date": str(new_date)
                    })

        return {"sfg_updates": [], "fg_updates": fg_updates}

    # Case 2: SFGs exist - use original logic
    # Build mapping: raw_material -> list of SFGs that use it (with their BOMs)
    sfg_bom_map = {}  # production_item -> {bom_no, schedule_date, row_name}
    for row in doc.sub_assembly_items:
        if row.production_item and row.bom_no and row.schedule_date:
            sfg_bom_map[row.production_item] = {
                "bom_no": row.bom_no,
                "schedule_date": row.schedule_date,
                "row_name": row.name,
                "parent_item_code": row.parent_item_code,
                "type_of_manufacturing": row.type_of_manufacturing
            }

    if not sfg_bom_map:
        return {"sfg_updates": [], "fg_updates": []}

    sfg_boms = list(set([info["bom_no"] for info in sfg_bom_map.values()]))
    changed_item_codes = list(changed_mr_items.keys())

    # Query BOM Item to find which SFGs use the changed raw materials
    bom_items_data = frappe.db.sql(
        """
        SELECT
            parent as bom_no,
            item_code
        FROM `tabBOM Item`
        WHERE parent IN %(bom_nos)s
          AND item_code IN %(raw_items)s
    """,
        {"bom_nos": sfg_boms, "raw_items": changed_item_codes},
        as_dict=True,
    )

    # Build mapping: raw_material -> list of BOMs
    raw_to_boms: dict[str, list[str]] = {}
    for row in bom_items_data:
        if row.item_code not in raw_to_boms:
            raw_to_boms[row.item_code] = []
        raw_to_boms[row.item_code].append(row.bom_no)

    # Get supplier lead times for changed items
    supplier_data = frappe.db.sql(
        """
        SELECT
            parent as item_code,
            supplier,
            lead_time_days
        FROM `tabItem Subcontracting Supplier`
        WHERE parent IN %(items)s
          AND company = %(company)s
          AND is_default = 1
    """,
        {"items": changed_item_codes, "company": doc.company},
        as_dict=True,
    )

    supplier_map = {s.item_code: s for s in supplier_data}

    # Calculate new SFG dates (Level 1: Direct children of changed raw materials)
    sfg_updates = []
    affected_sfgs: dict[str, datetime] = {}  # production_item -> new_schedule_date

    for item_code, change_info in changed_mr_items.items():
        new_start_date = change_info["new_start_date"]

        # Find SFGs that use this raw material
        if item_code in raw_to_boms:
            for bom_no in raw_to_boms[item_code]:
                # Find which SFG has this BOM
                for sfg_item, sfg_info in sfg_bom_map.items():
                    if sfg_info["bom_no"] == bom_no:
                        current_sfg_date = sfg_info["schedule_date"]

                        # Calculate new SFG date based on type_of_manufacturing
                        mfg_type = sfg_info.get("type_of_manufacturing")

                        if mfg_type == "Subcontract":
                            # For Subcontract: use supplier lead time
                            supplier_info = supplier_map.get(item_code)
                            lead_time = int(supplier_info.lead_time_days or 0) if supplier_info else 0

                            # new schedule_date = MR custom_start_date + lead_time
                            if lead_time > 0:
                                new_sfg_date = add_days(getdate(new_start_date), lead_time)
                            else:
                                new_sfg_date = getdate(new_start_date)

                            new_sfg_datetime = _to_datetime(new_sfg_date)

                        elif mfg_type == "In House":
                            # For In House: material arrival date = SFG start date (no lead time offset)
                            # The MR schedule_date IS when material arrives, which is when SFG can start
                            # So: SFG schedule_date = MR schedule_date (not custom_start_date!)

                            # But we changed custom_start_date, so schedule_date changed too
                            # We need to get the NEW schedule_date for this MR item
                            # schedule_date = custom_start_date + supplier_lead_time
                            supplier_info = supplier_map.get(item_code)
                            lead_time = int(supplier_info.lead_time_days or 0) if supplier_info else 0

                            # Calculate when material will arrive
                            material_arrival_date = add_days(getdate(new_start_date), lead_time) if lead_time > 0 else getdate(new_start_date)

                            # SFG can start when material arrives
                            new_sfg_datetime = _to_datetime(material_arrival_date)

                        else:
                            # Unknown type - skip
                            continue

                        # Only update if the new date is different
                        time_diff = abs((get_datetime(new_sfg_datetime) - get_datetime(current_sfg_date)).total_seconds())
                        if time_diff > 60:
                            # Calculate end_date for this SFG
                            if mfg_type == "Subcontract":
                                # Use lead time
                                lead_time_days = int(supplier_map.get(item_code).lead_time_days or 0) if supplier_map.get(item_code) else 0
                                new_sfg_end_date = add_days(getdate(new_sfg_datetime), lead_time_days)
                                new_sfg_end_datetime = _to_datetime(new_sfg_end_date)
                            elif mfg_type == "In House":
                                # Calculate production time
                                prod_time_result = calculate_production_time_from_bom(sfg_info["bom_no"])
                                production_mins = prod_time_result.get("production_minutes", 0)
                                new_sfg_end_datetime = add_to_date(get_datetime(new_sfg_datetime), minutes=production_mins)
                            else:
                                new_sfg_end_datetime = new_sfg_datetime

                            sfg_updates.append({
                                "row_name": sfg_info["row_name"],
                                "production_item": sfg_item,
                                "parent_item_code": sfg_info["parent_item_code"],
                                "current_date": str(current_sfg_date),
                                "new_date": str(new_sfg_datetime),
                                "affected_by_material": item_code,
                                "bom_no": sfg_info["bom_no"],
                                "type_of_manufacturing": mfg_type,
                                "custom_schedule_end_date": str(new_sfg_end_datetime)
                            })

                            # Track END date for cascade propagation (parent starts when child ends!)
                            if sfg_item not in affected_sfgs:
                                affected_sfgs[sfg_item] = new_sfg_end_datetime
                            else:
                                # Use the latest date if multiple materials affect same SFG
                                if new_sfg_end_datetime > affected_sfgs[sfg_item]:
                                    affected_sfgs[sfg_item] = new_sfg_end_datetime

    # Now cascade through parent SFGs recursively
    # Keep looping until no more parent SFGs are found
    max_iterations = 10  # Prevent infinite loops
    iteration = 0

    while affected_sfgs and iteration < max_iterations:
        iteration += 1
        new_affected_sfgs = {}

        # Check if any affected SFGs are children of other SFGs
        for affected_sfg_item, affected_sfg_date in affected_sfgs.items():
            # Find if this SFG is a child in another SFG's BOM
            for parent_sfg_item, parent_sfg_info in sfg_bom_map.items():
                # Skip if we're looking at the same item
                if parent_sfg_item == affected_sfg_item:
                    continue

                # Check if affected_sfg_item is in the BOM of parent_sfg_item
                parent_bom = parent_sfg_info["bom_no"]

                # Query if affected_sfg_item is in this parent's BOM
                is_child = frappe.db.exists(
                    "BOM Item",
                    {"parent": parent_bom, "item_code": affected_sfg_item}
                )

                if is_child:
                    # This SFG is a child of parent_sfg_item
                    # Calculate parent's new schedule_date based on child's new date + production time

                    # Calculate new parent dates based on manufacturing type
                    child_date = get_datetime(affected_sfg_date)
                    new_parent_date = child_date  # Parent starts when child ends

                    parent_mfg_type = parent_sfg_info.get("type_of_manufacturing")

                    if parent_mfg_type == "Subcontract":
                        # For Subcontract: use lead time days
                        # Get parent item code from parent_sfg_item (production_item)
                        parent_lead_time_days = get_subcontract_lead_time(
                            parent_sfg_item,
                            None,  # supplier will be fetched from default
                            doc.company
                        )
                        new_parent_end_date = add_days(getdate(child_date), parent_lead_time_days)
                        new_parent_end_date = _to_datetime(new_parent_end_date)
                    else:
                        # For In House: use production time from BOM operations
                        parent_bom_data = frappe.db.get_value(
                            "BOM",
                            parent_bom,
                            ["quantity"],
                            as_dict=True
                        )

                        if not parent_bom_data:
                            continue

                        parent_qty = float(parent_bom_data.get("quantity") or 1.0)

                        # Get production time for parent SFG
                        parent_operations = frappe.db.sql(
                            """
                            SELECT time_in_mins, custom_batchsize
                            FROM `tabBOM Operation`
                            WHERE parent = %s
                            ORDER BY idx
                        """,
                            (parent_bom,),
                            as_dict=True,
                        )

                        # Calculate production time in minutes
                        production_minutes = 0.0
                        for op in parent_operations:
                            time_in_mins = float(op.get("time_in_mins") or 0)
                            custom_batchsize = float(op.get("custom_batchsize") or 1)

                            if custom_batchsize <= 0:
                                custom_batchsize = 1

                            time_per_unit = time_in_mins / custom_batchsize
                            operation_time = time_per_unit * parent_qty
                            production_minutes += operation_time

                        new_parent_end_date = add_to_date(child_date, minutes=production_minutes)

                    current_parent_date = parent_sfg_info["schedule_date"]

                    # Check if this is a significant change
                    time_diff = abs((get_datetime(new_parent_date) - get_datetime(current_parent_date)).total_seconds())

                    if time_diff > 60:
                        # Check if this parent SFG is already in sfg_updates
                        existing_update = None
                        for update in sfg_updates:
                            if update["production_item"] == parent_sfg_item:
                                existing_update = update
                                break

                        if existing_update:
                            # Update existing entry if new date is later
                            if get_datetime(new_parent_date) > get_datetime(existing_update["new_date"]):
                                existing_update["new_date"] = str(new_parent_date)
                                existing_update["custom_schedule_end_date"] = str(new_parent_end_date)
                                existing_update["affected_by_sfg"] = affected_sfg_item
                        else:
                            # Add new update
                            sfg_updates.append({
                                "row_name": parent_sfg_info["row_name"],
                                "production_item": parent_sfg_item,
                                "parent_item_code": parent_sfg_info["parent_item_code"],
                                "current_date": str(current_parent_date),
                                "new_date": str(new_parent_date),
                                "custom_schedule_end_date": str(new_parent_end_date),
                                "affected_by_sfg": affected_sfg_item,
                                "bom_no": parent_bom
                            })

                        # Track this parent's END date for next iteration (grandparent starts when parent ends)
                        if parent_sfg_item not in new_affected_sfgs:
                            new_affected_sfgs[parent_sfg_item] = new_parent_end_date
                        else:
                            # Use the latest date if multiple children affect same parent
                            if new_parent_end_date > new_affected_sfgs[parent_sfg_item]:
                                new_affected_sfgs[parent_sfg_item] = new_parent_end_date

        # Continue with newly affected parent SFGs
        affected_sfgs = new_affected_sfgs

    # Calculate custom_schedule_end_date for all affected SFGs
    for sfg_update in sfg_updates:
        if "custom_schedule_end_date" not in sfg_update:
            # Calculate end date based on manufacturing type
            mfg_type = sfg_update.get("type_of_manufacturing")
            start_date = get_datetime(sfg_update["new_date"])

            if mfg_type == "Subcontract":
                # For Subcontract: use lead time days
                production_item = sfg_update.get("production_item")
                lead_time_days = get_subcontract_lead_time(
                    production_item,
                    None,  # supplier will be fetched from default
                    doc.company
                )
                end_date = add_days(getdate(start_date), lead_time_days)
                end_date = _to_datetime(end_date)
            else:
                # For In House: use production time from BOM operations
                bom_no = sfg_update["bom_no"]

                # Get BOM quantity
                bom_data = frappe.db.get_value("BOM", bom_no, ["quantity"], as_dict=True)
                qty = float(bom_data.get("quantity") or 1.0) if bom_data else 1.0

                # Get operations
                operations = frappe.db.sql(
                    """
                    SELECT time_in_mins, custom_batchsize
                    FROM `tabBOM Operation`
                    WHERE parent = %s
                    ORDER BY idx
                """,
                    (bom_no,),
                    as_dict=True,
                )

                # Calculate production time
                production_minutes = 0.0
                for op in operations:
                    time_in_mins = float(op.get("time_in_mins") or 0)
                    custom_batchsize = float(op.get("custom_batchsize") or 1)

                    if custom_batchsize <= 0:
                        custom_batchsize = 1

                    time_per_unit = time_in_mins / custom_batchsize
                    operation_time = time_per_unit * qty
                    production_minutes += operation_time

                # Calculate end date
                end_date = add_to_date(start_date, minutes=production_minutes)

            sfg_update["custom_schedule_end_date"] = str(end_date)

    # Now propagate SFG changes to FG items
    fg_updates = []

    if sfg_updates:
        # Build SFG data for FG calculation
        sfg_data_for_fg = []
        for sfg_update in sfg_updates:
            sfg_data_for_fg.append({
                "name": sfg_update["row_name"],
                "production_item": sfg_update["production_item"],
                "parent_item_code": sfg_update["parent_item_code"],
                "schedule_date": sfg_update["new_date"],
                "type_of_manufacturing": "Material Request Change"
            })

        # Create fake original dates (all current dates minus delta)
        original_sfg_dates = {}
        for sfg_update in sfg_updates:
            original_sfg_dates[sfg_update["row_name"]] = {
                "production_item": sfg_update["production_item"],
                "parent_item_code": sfg_update["parent_item_code"],
                "schedule_date": sfg_update["current_date"],
                "type_of_manufacturing": ""
            }

        # Call existing FG calculation method
        fg_impacts = calculate_fg_dates_from_subassembly(
            production_plan_name,
            sfg_data_for_fg,
            original_sfg_dates
        )

        fg_updates = fg_impacts

    return {
        "sfg_updates": sfg_updates,
        "fg_updates": fg_updates
    }


