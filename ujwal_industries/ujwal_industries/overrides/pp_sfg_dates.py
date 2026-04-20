# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""
SFG (Semi-Finished Goods / sub_assembly_items) date calculation functions for Production Plan.
Handles schedule_date calculations for sub-assembly items, onload data storage,
and reverse FG-date calculations from sub-assembly changes.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, getdate, get_datetime, now_datetime

from .pp_utils import (
    _skip_during_data_import,
    _get_allow_backdated_setting,
    _to_datetime,
    _as_timedelta,
    _subtract_minutes_from_datetime,
    _batch_fetch_subassembly_bom_operations,
    _batch_fetch_bom_operations,
    _get_supplier_lead_time,
    _calculate_production_minutes,
    _build_parent_chain,
    _fetch_shift_config,
    _get_effective_shift_config,
    _get_holiday_set,
    _prev_working_date,
    _backward_schedule,
    _current_shift_datetime,
    get_holiday_adjusted_date,
    shift_aware_forward_schedule,
    recalculate_finish_date,
)


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

    # Store original FG (po_items) dates
    if doc.get("po_items"):
        original_fg_dates = {}
        for row in doc.po_items:
            if row.item_code and (row.planned_start_date or row.custom_planned_end_date):
                original_fg_dates[row.name] = {
                    "item_code": row.item_code,
                    "planned_start_date": str(row.planned_start_date) if row.planned_start_date else None,
                    "custom_planned_end_date": str(row.custom_planned_end_date) if row.custom_planned_end_date else None,
                }
        doc.set_onload("original_fg_dates", original_fg_dates)

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

    row_defaults_by_name: dict[str, dict[str, Any]] = {}
    row_defaults_by_production_item: dict[str, dict[str, Any]] = {}

    # Some client flows send partial row payloads and omit fields like parent_item_code.
    # Hydrate those values from the current Production Plan rows so scheduling can proceed.
    if any(not item.get("parent_item_code") for item in inhouse_items):
        doc = frappe.get_doc("Production Plan", production_plan_name)
        for row in doc.get("sub_assembly_items") or []:
            row_info = {
                "name": row.name,
                "production_item": row.production_item,
                "parent_item_code": row.parent_item_code,
                "type_of_manufacturing": row.type_of_manufacturing,
                "bom_no": row.bom_no,
                "qty": row.qty,
                "schedule_date": row.schedule_date,
            }
            if row.name:
                row_defaults_by_name[row.name] = row_info
            if row.production_item and row.production_item not in row_defaults_by_production_item:
                row_defaults_by_production_item[row.production_item] = row_info

    # Process all items IN ORDER
    # For Subcontract items: just track their schedule_date for children to use
    # For In House items: calculate schedule_date and return it
    results: dict[str, Any] = {}

    for raw_item_info in inhouse_items:
        item_info = dict(raw_item_info)
        row_name = item_info.get("name")
        fallback_row = None
        if row_name and row_name in row_defaults_by_name:
            fallback_row = row_defaults_by_name[row_name]
        elif item_info.get("production_item") and item_info["production_item"] in row_defaults_by_production_item:
            fallback_row = row_defaults_by_production_item[item_info["production_item"]]

        if fallback_row:
            for fieldname in (
                "production_item",
                "parent_item_code",
                "type_of_manufacturing",
                "bom_no",
                "qty",
                "schedule_date",
            ):
                if not item_info.get(fieldname) and fallback_row.get(fieldname):
                    item_info[fieldname] = fallback_row[fieldname]

        production_item = item_info.get("production_item") or row_name or "Unknown Item"
        parent_item = item_info.get("parent_item_code")
        item_type = item_info.get("type_of_manufacturing", "In House")

        # Get base date: from schedule_date_map (which includes FG dates and Subcontract items)
        if parent_item and parent_item in schedule_date_map:
            base_date = schedule_date_map[parent_item]
        else:
            # Parent not found - this shouldn't happen if items are in correct order
            # Log a warning and use the FG date or now as fallback
            frappe.log_error(
                message=f"Parent item {parent_item or 'missing'} not found in schedule_date_map for {production_item}. Items may not be in correct order.",
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
                schedule_date_map[production_item] = schedule_date
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
            result_key = row_name or production_item
            results[result_key] = {
                "schedule_date": str(schedule_date),
                "custom_schedule_end_date": str(custom_schedule_end_date)
            }

            # Track for children - store the SCHEDULE_DATE (when production starts)
            # so children can use it as their end date
            schedule_date_map[production_item] = schedule_date

    return results


@frappe.whitelist()
def recalculate_sfg_chain_dates(
    production_plan_name: str,
    po_item_name: str,
    new_planned_start_date: str,
) -> dict[str, Any]:
    """
    Recalculate schedule dates for every SFG in a BOM chain when the parent
    FG's planned_start_date changes.

    Used by the Manage Dates dialog: when the user edits a po_item start date
    in Step 1, this function returns updated dates for all linked
    sub_assembly_items so Step 2 can reflect them immediately.

    Uses the same shift-aware backward scheduling as update_sub_assembly_dates:
    - In House  → _backward_schedule (510 net min/day)
    - Subcontract → deadline − grn_days (working) − lead_time (calendar)

    Args:
        production_plan_name: Production Plan document name.
        po_item_name: row name of the changed FG po_item (po_item.name).
        new_planned_start_date: New planned_start_date for that FG row (ISO datetime string).

    Returns:
        Dict mapping row_name → {schedule_date, custom_schedule_end_date}
        for ALL SFG rows in the chain (both In-House and Subcontract).
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)

    # Only process rows belonging to this chain, sorted top-down
    chain_rows = sorted(
        [r for r in (doc.sub_assembly_items or []) if (r.production_plan_item or "") == po_item_name],
        key=lambda r: (r.bom_level or 0),
    )
    if not chain_rows:
        return {}

    # Shift config — same helper used by update_sub_assembly_dates
    shift_config  = _get_effective_shift_config()
    holiday_list  = shift_config.get("holiday_list")
    holidays_set  = _get_holiday_set(holiday_list)
    _shift_start_raw = _as_timedelta(shift_config.get("start_time"))
    shift_start_td = _shift_start_raw if _shift_start_raw is not None else timedelta(hours=0)
    allow_backdated = _get_allow_backdated_setting()

    # FG item code — needed as the seed key in item_start_map
    po_item = next((p for p in (doc.po_items or []) if p.name == po_item_name), None)
    fg_item_code = po_item.item_code if po_item else ""

    # BOM operations cache (In-House items only)
    inhouse_bom_nos = [r.bom_no for r in chain_rows if r.bom_no and r.type_of_manufacturing != "Subcontract"]
    bom_time_cache: dict[str, list[dict[str, Any]]] = {}
    if inhouse_bom_nos:
        ops = frappe.db.sql(
            """
            SELECT parent AS bom_no, time_in_mins, custom_batchsize
            FROM `tabBOM Operation`
            WHERE parent IN %(boms)s
            ORDER BY parent, idx
            """,
            {"boms": inhouse_bom_nos},
            as_dict=True,
        )
        for op in ops:
            bom_time_cache.setdefault(op.bom_no, []).append(op)

    # GRN days + supplier lead times (Subcontract items only)
    subcontract_items = [r.production_item for r in chain_rows if r.type_of_manufacturing == "Subcontract"]
    grn_days_map: dict[str, int] = {}
    lead_time_by_rowname: dict[str, int] = {}
    if subcontract_items:
        raw_grn = frappe.db.sql(
            "SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days "
            "FROM `tabItem` WHERE name IN %(items)s",
            {"items": subcontract_items},
            as_dict=True,
        )
        grn_days_map = {d.name: int(d.grn_days) for d in raw_grn}
        for row in chain_rows:
            if row.type_of_manufacturing != "Subcontract":
                continue
            lead_time = 0
            if row.supplier:
                lead_time = _get_supplier_lead_time(row.production_item, row.supplier, doc.company)
            lead_time_by_rowname[row.name] = lead_time

    # Running map: production_item → schedule_date
    # Seeded with the FG item → new start date (the deadline for direct FG children)
    item_start_map: dict[str, Any] = {fg_item_code: get_datetime(new_planned_start_date)}

    # Per-row computed result (pass 1).  Keyed by row.name so pass 2 can update in place.
    item_data: dict[str, dict[str, Any]] = {}
    # production_item → row.name within this single chain (for cascade parent lookup)
    prod_item_to_rowname: dict[str, str] = {}

    # ════════════════════════════════════════════════════════════════════════
    # PASS 1 — top-down backward schedule (identical to set_subcontracting_suppliers)
    # ════════════════════════════════════════════════════════════════════════
    for row in chain_rows:
        parent_item = row.parent_item_code
        end_date: Any = item_start_map.get(parent_item) or get_datetime(new_planned_start_date)

        if row.type_of_manufacturing == "Subcontract":
            lead_time = lead_time_by_rowname.get(row.name, 0)
            grn_days  = grn_days_map.get(row.production_item, 0)

            receive_date = getdate(end_date)
            for _ in range(grn_days):
                receive_date = _prev_working_date(receive_date, holidays_set)
            sc_date    = getdate(add_days(receive_date, -lead_time))
            start_date: Any = datetime.combine(sc_date, datetime.min.time()) + shift_start_td

            if not allow_backdated and getdate(start_date) < getdate():
                start_date = _current_shift_datetime(shift_config)
                end_raw    = getdate(add_days(getdate(start_date), lead_time))
                end_date   = datetime.combine(
                    getdate(get_holiday_adjusted_date(end_raw, grn_days, holiday_list)),
                    datetime.min.time(),
                ) + shift_start_td

            item_data[row.name] = {
                "schedule_date": start_date,
                "end_date":      end_date,
                "time_type":     "lead_time",
                "lead_time":     lead_time,
                "grn_days":      grn_days,
                "prod_mins":     0.0,
            }

        else:
            prod_mins = _calculate_production_minutes(row.bom_no, row.qty, bom_time_cache)
            if prod_mins > 0:
                start_date = _backward_schedule(end_date, prod_mins, shift_config)
                if not allow_backdated and getdate(start_date) < getdate():
                    start_date = _current_shift_datetime(shift_config)
                    end_date   = shift_aware_forward_schedule(start_date, prod_mins, shift_config)
            else:
                start_date = end_date

            item_data[row.name] = {
                "schedule_date": start_date,
                "end_date":      end_date,
                "time_type":     "production_minutes",
                "lead_time":     0,
                "grn_days":      0,
                "prod_mins":     prod_mins,
            }

        item_start_map[row.production_item]    = start_date
        prod_item_to_rowname[row.production_item] = row.name

    # ════════════════════════════════════════════════════════════════════════
    # PASS 2 — bottom-up cascade (same as set_subcontracting_suppliers Pass 2)
    # If a child's end_date > parent's schedule_date, push the parent forward.
    # Repeat until stable (max 20 iterations for deep BOMs).
    # NOTE: we do NOT push the FG row — the caller provided the FG start explicitly.
    # ════════════════════════════════════════════════════════════════════════
    rows_bottom_up = sorted(chain_rows, key=lambda r: -(r.bom_level or 0))

    for _iter in range(20):
        any_change = False
        for row in rows_bottom_up:
            data = item_data.get(row.name)
            if not data:
                continue
            parent_item = row.parent_item_code
            this_end    = data["end_date"]

            # Find parent within the same chain; skip if parent is the FG item
            parent_rn   = prod_item_to_rowname.get(parent_item)
            if not parent_rn:
                continue  # parent is the FG — don't push it in dialog context

            parent_data = item_data.get(parent_rn)
            if not parent_data:
                continue

            if getdate(this_end) > getdate(parent_data["schedule_date"]):
                parent_data["schedule_date"] = this_end

                if parent_data["time_type"] == "lead_time":
                    lt  = parent_data["lead_time"]
                    grn = parent_data["grn_days"]
                    end_raw  = getdate(add_days(getdate(this_end), lt))
                    _end_adj = get_holiday_adjusted_date(end_raw, grn, holiday_list)
                    parent_data["end_date"] = (
                        datetime.combine(getdate(_end_adj), datetime.min.time()) + shift_start_td
                    )
                else:
                    parent_data["end_date"] = shift_aware_forward_schedule(
                        this_end, parent_data["prod_mins"], shift_config
                    )
                any_change = True

        if not any_change:
            break

    # ════════════════════════════════════════════════════════════════════════
    # PASS 2.5 — Restore FG start as end-date for direct FG children
    #
    # _backward_schedule strips the time part of the deadline, so changing
    # only the time (e.g. 17:20 → 18:00) on the same day yields an identical
    # backward-scheduled start for level-0 SFGs.  The cascade then replaces
    # their end_date with a forward-scheduled result that ignores the original
    # FG time component.  We restore the FG planned_start_date as the
    # "ready-by" deadline whenever the cascade result is earlier.
    # ════════════════════════════════════════════════════════════════════════
    fg_start_dt = get_datetime(new_planned_start_date)
    for row in chain_rows:
        if (row.parent_item_code or "") == fg_item_code:
            data = item_data.get(row.name)
            if data and get_datetime(data["end_date"]) < fg_start_dt:
                data["end_date"] = fg_start_dt

    # ════════════════════════════════════════════════════════════════════════
    # PASS 3 — collect final results
    # ════════════════════════════════════════════════════════════════════════
    return {
        rn: {
            "schedule_date":            str(d["schedule_date"]),
            "custom_schedule_end_date": str(d["end_date"]),
        }
        for rn, d in item_data.items()
    }


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


def set_subcontracting_suppliers(doc: Document, method: str | None = None) -> None:
    """
    Auto-populate suppliers, warehouses, and calculate schedule_date for SFG items.

    Algorithm (SAP-style top-down backward + bottom-up cascade):

    PASS 1 – TOP-DOWN (level 0 first, then 1, 2 …):
      Each SFG's deadline (custom_schedule_end_date) = parent's schedule_date.
      schedule_date = backward-schedule from deadline by production duration.
      If the backward result is in the past → Forward Jump:
        schedule_date = shift-clamped now
        custom_schedule_end_date = forward-schedule from schedule_date

    PASS 2 – BOTTOM-UP CASCADE (SAP "Reschedule the Top Level"):
      If any SFG's custom_schedule_end_date > its parent's schedule_date,
      push the parent's schedule_date (and its own end_date) forward.
      Cascade continues up to the FG level:
        FG.planned_start_date is pushed and FG.custom_planned_end_date is recalculated.
      Repeat until stable (max 20 iterations).

    PASS 3 – APPLY final dates to row fields.

    Shift awareness: always 510 net min/day (10:00–19:00, 30-min lunch).
    Falls back to _DEFAULT_SHIFT_CONFIG when Manufacturing Settings has no shift.

    Args:
        doc: Production Plan document
        method: Hook method name (unused)
    """
    del method  # Unused but required for hook signature
    # AVI
    if _skip_during_data_import():
        return
    # AVI

    if not doc.get("sub_assembly_items"):
        return
    
    if doc.custom_parallel_planning == 1:
        return
    
    # ── FG row collection: item_code → list of po_item rows ─────────────────
    # Used in Pass 2 Case A to check whether an SFG's parent is an FG item.
    # Per-chain keying (via production_plan_item) ensures each chain only pushes
    # its own FG row, not every FG row that happens to share the same item_code.
    fg_po_items: dict[str, list] = {}
    for po_item in doc.get("po_items") or []:
        if po_item.item_code and po_item.planned_start_date:
            fg_po_items.setdefault(po_item.item_code, []).append(po_item)

    # ── Batch fetches ─────────────────────────────────────────────────────────
    subcontract_items: list[str] = [
        d.production_item for d in doc.sub_assembly_items
        if d.type_of_manufacturing in ("Subcontract", "In House - Vendor")
    ]
    all_production_items: list[str] = [
        d.production_item for d in doc.sub_assembly_items if d.production_item
    ]

    # Default suppliers + lead times
    supplier_map: dict[str, Any] = {}
    if subcontract_items:
        raw = frappe.db.sql(
            """
            SELECT parent AS item_code, supplier, lead_time_days
            FROM `tabItem Subcontracting Supplier`
            WHERE parent IN %(items)s AND company = %(company)s AND is_default = 1
            """,
            {"items": subcontract_items, "company": doc.company},
            as_dict=True,
        )
        supplier_map = {s.item_code: s for s in raw}

    # Default warehouses
    warehouse_map: dict[str, str] = {}
    if all_production_items:
        raw = frappe.db.sql(
            """
            SELECT parent AS item_code, default_warehouse
            FROM `tabItem Default`
            WHERE parent IN %(items)s AND company = %(company)s
              AND default_warehouse IS NOT NULL AND default_warehouse != ''
            """,
            {"items": all_production_items, "company": doc.company},
            as_dict=True,
        )
        warehouse_map = {w.item_code: w.default_warehouse for w in raw}

    # GRN processing days (Subcontract items only)
    grn_days_map: dict[str, int] = {}
    if subcontract_items:
        raw = frappe.db.sql(
            """
            SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days
            FROM `tabItem` WHERE name IN %(items)s
            """,
            {"items": subcontract_items},
            as_dict=True,
        )
        grn_days_map = {d.name: int(d.grn_days) for d in raw}

    # BOM operation caches
    sfg_bom_cache = _batch_fetch_subassembly_bom_operations(doc)
    fg_bom_cache  = _batch_fetch_bom_operations(doc)  # needed for FG cascade push

    # ── Shift config: always 510 net min/day (10:00–19:00, 30-min lunch) ─────
    shift_config = _get_effective_shift_config()
    holiday_list = shift_config.get("holiday_list")
    holidays_set = _get_holiday_set(holiday_list)

    # shift_start_td is used to place Subcontract dates at the correct shift time
    # instead of midnight (00:00:00). Subcontract events (order placed / goods received)
    # happen at the start of the working day.
    _shift_start_raw = _as_timedelta(shift_config.get("start_time"))
    shift_start_td = _shift_start_raw if _shift_start_raw is not None else timedelta(hours=0)

    allow_backdated = _get_allow_backdated_setting()

    # ── Sort rows top-down so parents are always computed before children ─────
    # ERPNext stores level 0 = direct FG child, level N = deepest leaf.
    rows_sorted = sorted(doc.sub_assembly_items, key=lambda r: (r.bom_level or 0))

    # Running "current start" map: (production_plan_item, item_code) → datetime.
    # Per-chain keying fixes the overwrite bug: when the same production_item appears
    # in multiple independent BOM chains (combine_items=0 with duplicate FG item_codes),
    # each chain has its own start-date tracked separately.
    # Seeded with each FG po_item's planned_start_date under its own row name.
    item_start_map: dict[tuple[str, str], Any] = {}
    for _po in doc.get("po_items") or []:
        if _po.item_code and _po.planned_start_date and _po.name:
            item_start_map[(_po.name, _po.item_code)] = get_datetime(_po.planned_start_date)

    # Per-row computed result: row.name (unique) → data dict.
    # Keying by row.name prevents last-chain-wins overwrite for duplicate production_items.
    item_data: dict[str, dict[str, Any]] = {}

    # Secondary index: (production_plan_item, production_item) → row.name.
    # Allows Pass 2 to resolve a parent SFG within the same chain without scanning all rows.
    chain_item_to_rowname: dict[tuple[str, str], str] = {}

    # ════════════════════════════════════════════════════════════════════════
    # PASS 1 – TOP-DOWN: backward-schedule each SFG from its parent's start
    # ════════════════════════════════════════════════════════════════════════
    for row in rows_sorted:
        # Auto-populate fg_warehouse
        if not row.fg_warehouse and row.production_item in warehouse_map:
            row.fg_warehouse = warehouse_map[row.production_item]

        parent_item = row.parent_item_code

        # Deadline for this SFG = when its parent starts production (per-chain lookup)
        _chain_id   = row.production_plan_item or ""
        parent_start = item_start_map.get((_chain_id, parent_item))
        if not parent_start:
            parent_start = _current_shift_datetime(shift_config)

        end_date: Any = get_datetime(parent_start)  # = custom_schedule_end_date
        was_jumped = False

        supplier_info = supplier_map.get(row.production_item) if row.type_of_manufacturing in ("Subcontract", "In House - Vendor") else None
        if row.type_of_manufacturing in ("Subcontract", "In House - Vendor") and not row.supplier and supplier_info:
            row.supplier = supplier_info.supplier

        if row.type_of_manufacturing == "Subcontract":
            # ── SUBCONTRACT ─────────────────────────────────────────────────
            lead_time = 0
            if supplier_info:
                lead_time = int(supplier_info.lead_time_days or 0)
            elif row.supplier:
                lead_time = _get_supplier_lead_time(
                    row.production_item, row.supplier, doc.company
                )

            grn_days = grn_days_map.get(row.production_item, 0)

            # Backward: deadline − grn_days (working) − lead_time (calendar)
            receive_date = getdate(end_date)
            for _grn in range(grn_days):
                receive_date = _prev_working_date(receive_date, holidays_set)
            _sc_date = getdate(add_days(receive_date, -lead_time))
            # Place at shift_start (not midnight) so child SFGs use a proper shift time
            start_date: Any = datetime.combine(_sc_date, datetime.min.time()) + shift_start_td

            if not allow_backdated and getdate(start_date) < getdate():
                # Forward jump: start now, forward-schedule end
                start_date = _current_shift_datetime(shift_config)
                end_raw = getdate(add_days(getdate(start_date), lead_time))
                _end_date = get_holiday_adjusted_date(end_raw, grn_days, holiday_list)
                end_date = datetime.combine(getdate(_end_date), datetime.min.time()) + shift_start_td
                was_jumped = True

            item_data[row.name] = {
                "row": row,
                "schedule_date": start_date,
                "end_date": end_date,
                "time_type": "lead_time",
                "lead_time": lead_time,
                "grn_days": grn_days,
                "prod_mins": 0.0,
                "was_jumped": was_jumped,
            }

        else:
            # ── IN HOUSE ────────────────────────────────────────────────────
            prod_mins = _calculate_production_minutes(
                row.bom_no, row.qty, sfg_bom_cache
            )

            if prod_mins > 0:
                # Shift-aware backward schedule (always 510 net min/day)
                start_date = _backward_schedule(end_date, prod_mins, shift_config)

                if not allow_backdated and getdate(start_date) < getdate():
                    # Forward jump: start at shift-clamped now, forward-schedule end
                    start_date = _current_shift_datetime(shift_config)
                    end_date = shift_aware_forward_schedule(start_date, prod_mins, shift_config)
                    was_jumped = True
            else:
                start_date = end_date

            item_data[row.name] = {
                "row": row,
                "schedule_date": start_date,
                "end_date": end_date,
                "time_type": "production_minutes",
                "lead_time": 0,
                "grn_days": 0,
                "prod_mins": prod_mins,
                "was_jumped": was_jumped,
            }

        # Record this item's start so its children can use it as their deadline.
        # Per-chain key prevents siblings in other BOM chains from clobbering this entry.
        item_start_map[(_chain_id, row.production_item)] = start_date
        chain_item_to_rowname[(_chain_id, row.production_item)] = row.name

    # ════════════════════════════════════════════════════════════════════════
    # PASS 2 – BOTTOM-UP CASCADE (SAP "Reschedule the Top Level")
    # Process deepest items first; push parents (and finally FG) forward
    # when a child's end_date exceeds the parent's schedule_date (start).
    # Repeat until no more changes (max 20 iterations for deep BOMs).
    # ════════════════════════════════════════════════════════════════════════
    rows_bottom_up = sorted(doc.sub_assembly_items, key=lambda r: -(r.bom_level or 0))

    for _iter in range(20):
        any_change = False

        for row in rows_bottom_up:
            data = item_data.get(row.name)
            if not data:
                continue

            parent_item = row.parent_item_code
            this_end    = data["end_date"]

            # ── Case A: parent is an FG item ─────────────────────────────
            if parent_item in fg_po_items:
                # Push only the FG row that belongs to THIS chain.
                # row.production_plan_item holds the FG po_item row name for every
                # row in the chain (set by ERPNext's explode-BOM routine).
                # This ensures Chain 1's late SFG doesn't incorrectly push Chain 2's FG.
                target_fg_name = row.production_plan_item
                for po_item in fg_po_items[parent_item]:
                    if po_item.name != target_fg_name:
                        continue

                    fg_start = get_datetime(po_item.planned_start_date)
                    if getdate(this_end) > getdate(fg_start):
                        # Push FG's planned_start_date forward
                        po_item.planned_start_date = str(this_end)
                        # Keep item_start_map in sync for subsequent cascade iterations
                        item_start_map[(po_item.name, po_item.item_code)] = get_datetime(this_end)

                        # Recalculate FG's custom_planned_end_date (forward schedule)
                        fg_prod_mins = _calculate_production_minutes(
                            po_item.bom_no, po_item.planned_qty, fg_bom_cache
                        )
                        if fg_prod_mins > 0:
                            po_item.custom_planned_end_date = str(
                                shift_aware_forward_schedule(this_end, fg_prod_mins, shift_config)
                            )

                        # Mark this FG item_code so master_set_fg_dates_by_type
                        # does NOT overwrite the cascade-pushed dates with a fresh
                        # delivery_date − prod_time calculation.
                        if not hasattr(doc, "_fg_cascade_pushed"):
                            doc._fg_cascade_pushed: set[str] = set()
                        doc._fg_cascade_pushed.add(parent_item)

                        any_change = True
                    break

            # ── Case B: parent is another SFG ────────────────────────────
            else:
                # Locate the parent row within the same BOM chain using the secondary index.
                # Without per-chain keying, two chains sharing the same parent_item_code
                # would both look up the same (overwritten) entry and corrupt each other.
                _row_chain_id   = row.production_plan_item or ""
                parent_chain_key = (_row_chain_id, parent_item)
                parent_row_name  = chain_item_to_rowname.get(parent_chain_key)
                parent_data      = item_data.get(parent_row_name) if parent_row_name else None
                if not parent_data:
                    continue

                parent_start = parent_data["schedule_date"]
                if getdate(this_end) > getdate(parent_start):
                    # Push parent's start to when this child finishes
                    parent_data["schedule_date"]     = this_end
                    item_start_map[parent_chain_key] = this_end

                    # Recalculate parent's end_date
                    if parent_data["time_type"] == "lead_time":
                        lt  = parent_data["lead_time"]
                        grn = parent_data["grn_days"]
                        end_raw = getdate(add_days(getdate(this_end), lt))
                        _end_date = get_holiday_adjusted_date(end_raw, grn, holiday_list)
                        # Use shift_start (not midnight) so the next ancestor's
                        # schedule_date is placed within working hours.
                        parent_data["end_date"] = (
                            datetime.combine(getdate(_end_date), datetime.min.time()) + shift_start_td
                        )
                    else:
                        parent_data["end_date"] = shift_aware_forward_schedule(
                            this_end, parent_data["prod_mins"], shift_config
                        )
                    any_change = True

        if not any_change:
            break

    # ════════════════════════════════════════════════════════════════════════
    # PASS 2.5 – Restore FG start as end-date for direct FG children
    # Same rationale as recalculate_sfg_chain_dates: when the FG time changes
    # within the same date, the cascade forward-schedule may produce an end
    # earlier than the FG planned_start.  Restore the FG start as the deadline.
    # ════════════════════════════════════════════════════════════════════════
    for row in rows_sorted:
        if row.parent_item_code not in fg_po_items:
            continue
        data = item_data.get(row.name)
        if not data:
            continue
        chain_id = row.production_plan_item or ""
        fg_start = item_start_map.get((chain_id, row.parent_item_code))
        if fg_start and get_datetime(data["end_date"]) < get_datetime(fg_start):
            data["end_date"] = get_datetime(fg_start)

    # ════════════════════════════════════════════════════════════════════════
    # PASS 3 – APPLY final dates to row fields
    # ════════════════════════════════════════════════════════════════════════
    adjustments_made: list[dict[str, Any]] = []

    for _row_name, data in item_data.items():
        data["row"].schedule_date            = data["schedule_date"]
        data["row"].custom_schedule_end_date = data["end_date"]

        if data["was_jumped"]:
            if data["time_type"] == "lead_time":
                time_str = f"{data['lead_time']} days"
            else:
                # Express In House duration as working-days (510 min/day standard)
                time_str = f"{data['prod_mins'] / 510:.1f} working-days"

            adjustments_made.append({
                "idx":      data["row"].idx,
                "item":     data["row"].production_item,
                "type":     data["row"].type_of_manufacturing,
                "time":     time_str,
                "schedule": getdate(data["schedule_date"]),
                "end":      getdate(data["end_date"]),
            })

    if adjustments_made:
        max_end_date = max(adj["end"] for adj in adjustments_made)
        details = "<br>".join([
            f"Row #{adj['idx']} ({adj['item']}): {adj['type']}, {adj['time']}, "
            f"Schedule={frappe.format(adj['schedule'], 'Date')}, "
            f"End={frappe.format(adj['end'], 'Date')}"
            for adj in adjustments_made
        ])
        frappe.msgprint(
            msg=_(
                "Sub Assembly items adjusted due to backdating constraints:<br><br>"
                "{0}<br><br>"
                "⚠️ Latest item ready by <b>{1}</b>."
            ).format(details, frappe.format(max_end_date, "Date")),
            title=_("Sub Assembly Schedule Adjusted"),
            indicator="orange",
        )


@frappe.whitelist()
def recalculate_sfg_chain_upward(
    production_plan_name: str,
    changed_sfg_name: str,
    new_end_date: str,
    fg_start_override: str | None = None,
) -> dict[str, Any]:
    """
    When the user manually sets an SFG's end date in the Manage Dates dialog,
    cascade the change UPWARD through every ancestor SFG in the same BOM chain
    and (if needed) push the FG's planned_start_date too.

    Handles all BOM depths:
      level-0 (direct FG child) → only FG may be pushed.
      level-1, level-2, … → each ancestor SFG between the changed item and the
        FG is re-evaluated; if its schedule_date is now earlier than the child's
        new end_date it is pushed and its own end_date is recalculated.

    Args:
        production_plan_name: Production Plan document name.
        changed_sfg_name: row.name of the SFG whose end date was changed.
        new_end_date: The new custom_schedule_end_date for the changed SFG (ISO string).
        fg_start_override: The caller's current in-memory FG planned_start_date.
            When provided, the FG-update condition is evaluated against this value
            instead of the DB value — prevents stale-DB mismatch when the user
            makes multiple unsaved cascades in the same session.

    Returns:
        {
          "sfg_updates": {row_name: {"schedule_date": ..., "custom_schedule_end_date": ...}},
          "fg_update":   {po_item_name: {"planned_start_date": ..., "custom_planned_end_date": ...}}
        }
        Both dicts are empty when nothing upstream needs to move.
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)
    if not doc.get("sub_assembly_items"):
        return {"sfg_updates": {}, "fg_update": {}}

    # Locate the changed SFG row
    changed_row = next(
        (r for r in doc.sub_assembly_items if r.name == changed_sfg_name), None
    )
    if not changed_row:
        return {"sfg_updates": {}, "fg_update": {}}

    chain_id = changed_row.production_plan_item or ""

    # Collect all rows in the same BOM chain
    chain_rows = [r for r in doc.sub_assembly_items if (r.production_plan_item or "") == chain_id]

    # production_item → row  (each item appears once per chain)
    item_to_row: dict[str, Any] = {r.production_item: r for r in chain_rows}

    # Shift config — used for backdating guard + FG end-date forward-scheduling
    shift_config  = _get_effective_shift_config()

    # Duration cache for each ancestor: (end - start) from saved doc.
    # Using saved durations rather than recomputing from BOM/lead-time ensures that:
    #   1. Going back to the original date restores the original values exactly.
    #   2. Cascade shifts dates without replanning production times.
    ancestor_duration_map: dict[str, Any] = {}
    for r in chain_rows:
        if r.schedule_date and r.custom_schedule_end_date:
            ancestor_duration_map[r.name] = (
                get_datetime(r.custom_schedule_end_date) - get_datetime(r.schedule_date)
            )

    # FG po_item for this chain
    po_item = next((po for po in (doc.po_items or []) if po.name == chain_id), None)
    fg_item_code = po_item.item_code if po_item else ""

    allow_backdated   = _get_allow_backdated_setting()
    sfg_updates: dict[str, dict[str, Any]] = {}
    fg_update:   dict[str, dict[str, Any]] = {}
    clamped_ancestors = False

    # ── Walk the full chain upward from changed_row (both forward and backward cascade) ─
    # Each ancestor always starts immediately when its direct child finishes (tight chain).
    push_end: Any = get_datetime(new_end_date)
    current_item  = changed_row.parent_item_code

    while current_item and current_item != fg_item_code:
        ancestor = item_to_row.get(current_item)
        if not ancestor:
            break

        # Tight-chain scheduling: ancestor always starts when its child ends
        new_start: Any = push_end

        # Backdating guard: if cascade would place ancestor start in the past, clamp to now
        if not allow_backdated and getdate(new_start) < getdate():
            new_start = _current_shift_datetime(shift_config)
            clamped_ancestors = True

        # Preserve the ancestor's original production duration — shift dates, don't replan.
        saved_duration = ancestor_duration_map.get(ancestor.name)
        if saved_duration is not None and saved_duration.total_seconds() > 0:
            new_end_ancestor: Any = new_start + saved_duration
        else:
            new_end_ancestor = new_start

        sfg_updates[ancestor.name] = {
            "schedule_date":            str(new_start),
            "custom_schedule_end_date": str(new_end_ancestor),
        }
        push_end     = new_end_ancestor
        current_item = ancestor.parent_item_code

    # ── Check if the FG itself needs to move ────────────────────────────────────
    if current_item == fg_item_code and po_item:
        # Prefer the caller's in-memory value (fg_start_override) over the DB value
        # so that multiple unsaved cascades in the same session stay consistent.
        _fg_start_raw = fg_start_override or (po_item.planned_start_date if po_item.planned_start_date else None)
        fg_start = get_datetime(_fg_start_raw) if _fg_start_raw else None
        if fg_start is None or push_end != fg_start:
            fg_bom_cache   = _batch_fetch_bom_operations(doc)
            fg_prod_mins   = _calculate_production_minutes(po_item.bom_no, po_item.planned_qty, fg_bom_cache)
            new_fg_end: Any = (
                shift_aware_forward_schedule(push_end, fg_prod_mins, shift_config)
                if fg_prod_mins > 0 else push_end
            )
            fg_update[po_item.name] = {
                "planned_start_date":    str(push_end),
                "custom_planned_end_date": str(new_fg_end),
            }

    return {"sfg_updates": sfg_updates, "fg_update": fg_update, "clamped_ancestors": clamped_ancestors}


@frappe.whitelist()
def recalculate_sfg_row_dates(
    production_plan_name: str,
    sfg_row_name: str,
    changed_field: str,   # "schedule_date" or "custom_schedule_end_date"
    new_value: str,
    override_mfg_type: str | None = None,
    override_supplier: str | None = None,
) -> dict[str, str]:
    """
    Bidirectional single-row date recalculation for SFG items in the Manage Dates dialog.

    - schedule_date changed        → recalculate custom_schedule_end_date (forward schedule)
    - custom_schedule_end_date changed → recalculate schedule_date        (backward schedule)

    In House:    shift-aware production minutes (510 net min/day)
    Subcontract: lead_time (calendar days) + GRN days (working days)

    override_mfg_type / override_supplier: dialog values take precedence over the saved doc,
    allowing the user to change type/supplier in the dialog and get correct dates immediately.

    Returns:
        {"schedule_date": "...", "custom_schedule_end_date": "..."}
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)
    row = next((r for r in (doc.sub_assembly_items or []) if r.name == sfg_row_name), None)
    if not row:
        return {}

    # Use dialog-provided values when available (dialog has not yet been saved)
    effective_mfg_type = override_mfg_type or row.type_of_manufacturing or "In House"
    effective_supplier = override_supplier if override_mfg_type else (row.supplier or "")

    shift_config    = _get_effective_shift_config()
    holiday_list    = shift_config.get("holiday_list")
    holidays_set    = _get_holiday_set(holiday_list)
    _shift_start_raw = _as_timedelta(shift_config.get("start_time"))
    shift_start_td  = _shift_start_raw if _shift_start_raw is not None else timedelta(hours=0)
    allow_backdated = _get_allow_backdated_setting()

    if effective_mfg_type == "Subcontract":
        lead_time = (
            _get_supplier_lead_time(row.production_item, effective_supplier, doc.company)
            if effective_supplier else 0
        )
        grn_raw = frappe.db.sql(
            "SELECT COALESCE(custom_expected_grn_processing_days, 0) AS grn_days "
            "FROM `tabItem` WHERE name = %(item)s",
            {"item": row.production_item},
            as_dict=True,
        )
        grn_days = int(grn_raw[0].grn_days) if grn_raw else 0

        if changed_field == "schedule_date":
            # Start → End: start + lead_time (calendar) + GRN working days
            new_start: Any = get_datetime(new_value)
            end_raw = getdate(add_days(getdate(new_start), lead_time))
            end_adj = get_holiday_adjusted_date(end_raw, grn_days, holiday_list)
            end_dt: Any = datetime.combine(getdate(end_adj), datetime.min.time()) + shift_start_td
            return {
                "schedule_date":            str(new_start),
                "custom_schedule_end_date": str(end_dt),
            }
        else:
            # End → Start: go back GRN working days, then back lead_time calendar days
            new_end: Any = get_datetime(new_value)
            receive_date = getdate(new_end)
            for _ in range(grn_days):
                receive_date = _prev_working_date(receive_date, holidays_set)
            sc_date   = getdate(add_days(receive_date, -lead_time))
            start_dt: Any = datetime.combine(sc_date, datetime.min.time()) + shift_start_td

            clamped = False
            # Backdate guard: clamp start to now, forward-schedule end from clamped start
            if not allow_backdated and getdate(start_dt) < getdate():
                start_dt = _current_shift_datetime(shift_config)
                end_raw  = getdate(add_days(getdate(start_dt), lead_time))
                end_adj  = get_holiday_adjusted_date(end_raw, grn_days, holiday_list)
                new_end  = datetime.combine(getdate(end_adj), datetime.min.time()) + shift_start_td
                clamped  = True

            return {
                "schedule_date":            str(start_dt),
                "custom_schedule_end_date": str(new_end),
                "clamped":                  clamped,
            }

    else:
        # In House — production minutes from BOM
        bom_cache: dict[str, list[dict[str, Any]]] = {}
        if row.bom_no:
            ops = frappe.db.sql(
                "SELECT parent AS bom_no, time_in_mins, custom_batchsize "
                "FROM `tabBOM Operation` WHERE parent = %(bom)s ORDER BY idx",
                {"bom": row.bom_no},
                as_dict=True,
            )
            bom_cache[row.bom_no] = list(ops)

        prod_mins = _calculate_production_minutes(row.bom_no, row.qty, bom_cache)

        if changed_field == "schedule_date":
            new_start = get_datetime(new_value)
            end_dt = (
                shift_aware_forward_schedule(new_start, prod_mins, shift_config)
                if prod_mins > 0 else new_start
            )
            return {
                "schedule_date":            str(new_start),
                "custom_schedule_end_date": str(end_dt),
            }
        else:
            clamped = False
            new_end = get_datetime(new_value)
            if prod_mins > 0:
                start_dt = _backward_schedule(new_end, prod_mins, shift_config)
                # Backdate guard: clamp start to now, forward-schedule end from clamped start
                if not allow_backdated and getdate(start_dt) < getdate():
                    start_dt = _current_shift_datetime(shift_config)
                    new_end  = shift_aware_forward_schedule(start_dt, prod_mins, shift_config)
                    clamped  = True
            else:
                start_dt = new_end
            return {
                "schedule_date":            str(start_dt),
                "custom_schedule_end_date": str(new_end),
                "clamped":                  clamped,
            }


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
