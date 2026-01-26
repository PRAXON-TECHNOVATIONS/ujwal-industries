# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Optional

import frappe
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, add_to_date, getdate, get_datetime, now_datetime

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
    
    if not doc.get("po_items"):
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
                row.planned_start_date = _to_datetime(new_date)

            # === IN HOUSE LOGIC ===
            elif mfg_type == "In House":
                row.custom_supplier = None # Clear Supplier
                
                prod_minutes = _calculate_production_minutes(
                    row.bom_no, row.planned_qty, bom_time_cache
                )
                
                if prod_minutes > 0:
                    row.planned_start_date = _subtract_minutes_from_datetime(
                        delivery_dt_obj, prod_minutes
                    )
                else:
                    row.planned_start_date = delivery_dt_obj

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
    _ = method  # Unused but required for hook signature

    # Store original sub-assembly schedule dates
    if doc.get("sub_assembly_items"):
        original_dates = {}
        for row in doc.sub_assembly_items:
            if row.production_item and row.schedule_date:
                original_dates[row.name] = {
                    "production_item": row.production_item,
                    "parent_item_code": row.parent_item_code,
                    "schedule_date": str(row.schedule_date),
                    "type_of_manufacturing": row.type_of_manufacturing
                }
        doc.set_onload("original_subassembly_dates", original_dates)

    # Store original MR item dates
    if doc.get("mr_items"):
        original_mr_dates = {}
        for row in doc.mr_items:
            if row.item_code and hasattr(row, 'custom_start_date') and row.custom_start_date:
                original_mr_dates[row.name] = {
                    "item_code": row.item_code,
                    "custom_start_date": str(row.custom_start_date),
                    "schedule_date": str(row.schedule_date) if row.schedule_date else None
                }
        doc.set_onload("original_mr_dates", original_mr_dates)


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
    _ = method  # Unused but required for hook signature

    # Only process Sales Order-based plans
    if doc.get("get_items_from") != "Sales Order":
        return

    if not doc.get("po_items"):
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
                po_item.planned_start_date = calculated_datetime
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

            # Set custom_schedule_end_date as when parent needs it
            custom_schedule_end_date = base_date

            # Calculate schedule_date by subtracting production time
            if production_minutes > 0:
                schedule_date = _subtract_minutes_from_datetime(base_date, production_minutes)
            else:
                schedule_date = base_date

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
    _ = method  # Unused but required for hook signature

    if not doc.get("sub_assembly_items"):
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

    # Track schedule_date for each production_item as we process
    # This allows child items to reference their parent's schedule_date
    schedule_date_map: dict[str, Any] = {}

    # Process items in order (they're ordered by BOM traversal: parent before children)
    for row in doc.sub_assembly_items:
        # Auto-populate fg_warehouse from Item Default if not already set
        if not row.fg_warehouse and row.production_item in warehouse_map:
            row.fg_warehouse = warehouse_map[row.production_item]

        # Determine the base date for this item
        # parent_item_code tells us which item this is a component of
        parent_item = row.parent_item_code

        # Get base date: either from FG (if parent is FG) or from parent's schedule_date
        if parent_item in fg_dates:
            # Direct child of FG item
            base_date = fg_dates[parent_item]
        elif parent_item in schedule_date_map:
            # Child of another sub-assembly item
            base_date = schedule_date_map[parent_item]
        else:
            # Fallback: use current schedule_date or now
            base_date = row.schedule_date or now_datetime()

        if row.type_of_manufacturing == "Subcontract":
            supplier_info = supplier_map.get(row.production_item)

            # Auto-populate supplier if not already set
            if not row.supplier and supplier_info:
                row.supplier = supplier_info.supplier

            # Calculate lead time for this item
            lead_time = 0
            if supplier_info:
                lead_time = int(supplier_info.lead_time_days or 0)
            elif row.supplier:
                # If supplier was manually set, try to get lead time for that supplier
                lead_time = _get_supplier_lead_time(
                    row.production_item, row.supplier, doc.company
                )

            # Calculate dates:
            # - schedule_date: When to send to supplier (base_date - lead_time)
            # - custom_schedule_end_date: When item must be ready (= base_date, i.e., when parent needs it)
            if lead_time > 0:
                schedule_date = add_days(getdate(base_date), -lead_time)
                row.schedule_date = _to_datetime(schedule_date)
                row.custom_schedule_end_date = get_datetime(base_date)
            else:
                row.schedule_date = get_datetime(base_date)
                row.custom_schedule_end_date = get_datetime(base_date)

            # Store this item's schedule_date for its children to reference
            schedule_date_map[row.production_item] = row.schedule_date
        else:
            # In-house items: Calculate based on BOM operations time
            production_minutes = _calculate_production_minutes(
                row.bom_no,
                row.qty,
                bom_time_cache
            )

            # Set custom_schedule_end_date as when parent needs it
            row.custom_schedule_end_date = get_datetime(base_date)

            # Calculate schedule_date by subtracting production time
            if production_minutes > 0:
                row.schedule_date = _subtract_minutes_from_datetime(
                    base_date, production_minutes
                )
            else:
                row.schedule_date = get_datetime(base_date)

            # Store this item's schedule_date for its children to reference
            schedule_date_map[row.production_item] = row.schedule_date


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

    for item_info in subassembly_data:
        row_name = item_info.get("name")
        prod_item = item_info.get("production_item")
        current_date_str = item_info.get("schedule_date")

        if not row_name or not prod_item or not current_date_str:
            continue

        # Check if we have original date for this row
        if row_name not in original_dates:
            # No original date - skip
            continue

        original_info = original_dates[row_name]
        original_date_str = original_info.get("schedule_date")

        if not original_date_str:
            continue

        # Compare dates
        current_date = get_datetime(current_date_str)
        original_date = get_datetime(original_date_str)

        # Calculate delta in seconds
        delta_seconds = (current_date - original_date).total_seconds()

        # Only consider significant changes (> 60 seconds)
        if abs(delta_seconds) > 60:
            changed_items[prod_item] = {
                "delta_minutes": delta_seconds / 60.0,
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

    For each raw material that is linked to SFGs (via BOM):
    1. Find all SFGs that use this raw material
    2. Get the lowest schedule_date from those SFGs
    3. Get the default supplier for the raw material
    4. Calculate MR schedule_date = lowest_sfg_date - supplier_lead_time_days
    5. Set custom_start_date = lowest_sfg_date

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

    if not doc.get("sub_assembly_items"):
        return {}

    # Extract all raw material item codes
    raw_material_items = [item["item_code"] for item in mr_items_data if item.get("item_code")]

    if not raw_material_items:
        return {}

    # Build mapping: raw_material -> list of SFGs that use it
    # We need to query BOM Item to find which SFGs (from sub_assembly_items) use each raw material

    # Get all SFG items from sub_assembly_items with their BOMs
    sfg_bom_map = {}  # production_item -> {bom_no, schedule_date}
    for row in doc.sub_assembly_items:
        if row.production_item and row.bom_no and row.schedule_date:
            sfg_bom_map[row.production_item] = {
                "bom_no": row.bom_no,
                "schedule_date": row.schedule_date
            }

    if not sfg_bom_map:
        return {}

    sfg_boms = list(set([info["bom_no"] for info in sfg_bom_map.values()]))

    # Query BOM Item table to find which raw materials are in which BOMs
    # We need to handle multi-level BOMs (raw materials might be in nested BOMs)
    bom_items_data = frappe.db.sql(
        """
        SELECT
            parent as bom_no,
            item_code
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

    # Now build: raw_material -> list of (sfg_item, schedule_date)
    raw_to_sfgs: dict[str, list[dict[str, Any]]] = {}

    for sfg_item, info in sfg_bom_map.items():
        bom_no = info["bom_no"]
        schedule_date = info["schedule_date"]

        if bom_no in bom_to_raw:
            for raw_item in bom_to_raw[bom_no]:
                if raw_item not in raw_to_sfgs:
                    raw_to_sfgs[raw_item] = []
                raw_to_sfgs[raw_item].append({
                    "sfg_item": sfg_item,
                    "schedule_date": schedule_date
                })

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
        # Find lowest schedule_date from SFGs that use this raw material
        if item_code not in raw_to_sfgs:
            # This raw material is not linked to any SFG
            # Skip custom date calculation
            continue

        sfg_dates = [get_datetime(sfg_info["schedule_date"]) for sfg_info in raw_to_sfgs[item_code]]
        lowest_sfg_date = min(sfg_dates)

        # Get supplier info
        supplier_info = supplier_map.get(item_code)

        # Only calculate dates if supplier is defined
        if not supplier_info or not supplier_info.supplier:
            # No default supplier defined - skip this item
            continue

        lead_time = int(supplier_info.lead_time_days or 0)
        supplier_name = supplier_info.supplier

        # custom_start_date = when to order from supplier (earliest date to place order)
        # schedule_date = when material is needed (when SFG production starts)
        if lead_time > 0:
            custom_start_date = add_days(getdate(lowest_sfg_date), -lead_time)
        else:
            custom_start_date = getdate(lowest_sfg_date)

        results[item_code] = {
            "custom_start_date": str(_to_datetime(custom_start_date)),
            "schedule_date": str(lowest_sfg_date),
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
    company: str | None = None
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

    Returns:
        Dict with parent_sfg_updates and mr_item_updates
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)

    if not company:
        company = doc.company

    parent_sfg_updates = []
    mr_item_updates = []

    # Cascade UP to parent SFGs
    if doc.get("sub_assembly_items"):
        for parent_row in doc.sub_assembly_items:
            if not parent_row.bom_no or parent_row.production_item == changed_sfg_item:
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
                child_end = get_datetime(new_end_date if new_end_date else new_schedule_date)
                new_parent_start = add_to_date(child_end, minutes=production_mins)
                new_parent_end = add_to_date(new_parent_start, minutes=production_mins)

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

    if not doc.get("sub_assembly_items") or not mr_items_data:
        return {"sfg_updates": [], "fg_updates": []}

    # Detect changes in MR items
    changed_mr_items: dict[str, dict[str, Any]] = {}

    for item_info in mr_items_data:
        row_name = item_info.get("name")
        item_code = item_info.get("item_code")
        current_start_date_str = item_info.get("custom_start_date")

        if not row_name or not item_code or not current_start_date_str:
            continue

        # Check if we have original date
        if row_name not in original_mr_dates:
            continue

        original_info = original_mr_dates[row_name]
        original_start_date_str = original_info.get("custom_start_date")

        if not original_start_date_str:
            continue

        # Compare dates
        current_date = get_datetime(current_start_date_str)
        original_date = get_datetime(original_start_date_str)

        # Calculate delta in seconds
        delta_seconds = (current_date - original_date).total_seconds()

        # Only consider significant changes (> 60 seconds)
        if abs(delta_seconds) > 60:
            changed_mr_items[item_code] = {
                "delta_minutes": delta_seconds / 60.0,
                "new_start_date": current_date
            }

    if not changed_mr_items:
        return {"sfg_updates": [], "fg_updates": []}

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
                            sfg_updates.append({
                                "row_name": sfg_info["row_name"],
                                "production_item": sfg_item,
                                "parent_item_code": sfg_info["parent_item_code"],
                                "current_date": str(current_sfg_date),
                                "new_date": str(new_sfg_datetime),
                                "affected_by_material": item_code,
                                "bom_no": sfg_info["bom_no"],
                                "type_of_manufacturing": mfg_type
                            })

                            # Track for cascade propagation
                            if sfg_item not in affected_sfgs:
                                affected_sfgs[sfg_item] = new_sfg_datetime
                            else:
                                # Use the latest date if multiple materials affect same SFG
                                if new_sfg_datetime > affected_sfgs[sfg_item]:
                                    affected_sfgs[sfg_item] = new_sfg_datetime

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

                    # Get the BOM and planned qty for parent
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

                    # Calculate new parent schedule_date = child schedule_date + production_time
                    child_date = get_datetime(affected_sfg_date)
                    new_parent_date = add_to_date(child_date, minutes=production_minutes)

                    # Also calculate custom_schedule_end_date (same as schedule_date + production time)
                    new_parent_end_date = add_to_date(new_parent_date, minutes=production_minutes)

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

                        # Track this parent for next iteration
                        if parent_sfg_item not in new_affected_sfgs:
                            new_affected_sfgs[parent_sfg_item] = new_parent_date
                        else:
                            # Use the latest date if multiple children affect same parent
                            if new_parent_date > new_affected_sfgs[parent_sfg_item]:
                                new_affected_sfgs[parent_sfg_item] = new_parent_date

        # Continue with newly affected parent SFGs
        affected_sfgs = new_affected_sfgs

    # Calculate custom_schedule_end_date for all affected SFGs
    for sfg_update in sfg_updates:
        if "custom_schedule_end_date" not in sfg_update:
            # Calculate end date based on production time
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
            start_date = get_datetime(sfg_update["new_date"])
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
