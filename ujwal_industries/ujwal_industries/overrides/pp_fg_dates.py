# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportPrivateUsage=false
"""
FG (Finished Goods / po_items) date calculation functions for Production Plan.
Handles planned_start_date calculations for FG items based on delivery dates,
BOM production times, and supplier lead times.
"""

from __future__ import annotations

import math
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, cint, getdate, get_datetime, now_datetime

from .pp_utils import (
    _skip_during_data_import,
    _get_allow_backdated_setting,
    _adjust_date_if_backdated,
    _should_override_planned_date,
    _to_datetime,
    _subtract_minutes_from_datetime,
    _batch_fetch_delivery_dates,
    _batch_fetch_bom_operations,
    _calculate_production_minutes,
    _get_delivery_date_from_cache,
    _fetch_shift_config,
    _get_effective_shift_config,
    get_adjusted_inhouse_start_date,
    get_adjusted_subcontract_start_date,
    get_holiday_adjusted_date,
    shift_aware_forward_schedule,
    clamp_to_current_shift,
    recalculate_finish_date,
)



def validate_planned_start_dates(doc: Document, method: str | None = None) -> None:
    """
    Validate and auto-adjust dates if backdated dates are not allowed.

    Validates all date fields across:
    - po_items (FG): planned_start_date
    - sub_assembly_items (SFG): schedule_date
    - mr_items: custom_start_date

    Checks Manufacturing Settings.allow_backdated_planned_start_date field.
    If unchecked (0):
    - In House items: Auto-adjusted by master_set_fg_dates_by_type (shift-clamped now)
    - Subcontract items: Auto-adjusted by master_set_fg_dates_by_type (forward jump to now)
    - Other/unknown types: Throw validation error

    Args:
        doc: Production Plan document
        method: Hook method name (unused)
    """
    del method  # Unused but required for hook signature
    # AVI
    if _skip_during_data_import():
        return
    # AVI

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

                if manufacturing_type in ("In House", "Subcontract"):
                    # Both types are auto-corrected by master_set_fg_dates_by_type
                    # (In House → shift-clamped now; Subcontract → now_datetime() forward jump).
                    # Never throw here — let the before_save hooks recalculate.
                    pass
                else:
                    # Unknown / unmanaged types: no auto-correction available.
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
    # AVI
    if _skip_during_data_import():
        return
    # AVI
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

    # Always shift-aware (510 net min/day fallback when shift not configured)
    shift_config = _get_effective_shift_config()

    # --- 2. MAIN LOGIC LOOP ---
    # FG items whose planned_start_date was cascade-pushed by set_subcontracting_suppliers
    # (which runs just before this hook) must NOT be overwritten with the baseline
    # delivery_date − prod_time calculation — the cascade date is always later and correct.
    cascade_pushed: set[str] = getattr(doc, "_fg_cascade_pushed", set())

    for row in target_rows:
        try:
            if row.item_code in cascade_pushed:
                # Dates already set correctly by SFG cascade — preserve them.
                continue

            mfg_type = row.get("custom_manufacturing_type")

            # Delivery Date logic
            delivery_date = _get_delivery_date_from_cache(row, combine_items, delivery_cache)
            if not delivery_date:
                continue

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

                planned_start = get_adjusted_subcontract_start_date(
                    delivery_dt_obj, lead_time, row.item_code, doc.company
                )

                # If calculated start is in the past, jump to now instead of erroring
                if getdate(planned_start) < getdate():
                    planned_start = now_datetime()

                row.planned_start_date = planned_start

                # End date = start + lead_time (calendar days) + GRN processing days (holiday-aware)
                # Ensures the final date is never on a holiday.
                grn_days = int(
                    frappe.db.get_value(
                        "Item", row.item_code, "custom_expected_grn_processing_days"
                    ) or 0
                )
                holiday_list = shift_config.get("holiday_list")
                end_date = getdate(add_days(getdate(planned_start), lead_time))
                end_date = get_holiday_adjusted_date(end_date, grn_days, holiday_list)
                row.custom_planned_end_date = str(_to_datetime(end_date))

            # === IN HOUSE LOGIC ===
            elif mfg_type == "In House":
                row.custom_supplier = None  # Clear Supplier

                prod_minutes = _calculate_production_minutes(
                    row.bom_no, row.planned_qty, bom_time_cache
                )

                if prod_minutes > 0:
                    planned_start = get_adjusted_inhouse_start_date(delivery_dt_obj, prod_minutes)
                    # get_adjusted_inhouse_start_date already handles backdating internally
                    row.planned_start_date = planned_start

                    # Forward-schedule finish from the clamped start
                    finish_dt = recalculate_finish_date(planned_start, prod_minutes, shift_config)
                    row.custom_planned_end_date = str(finish_dt)

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


def set_planned_start_dates(doc: Document, method: str | None = None) -> None:
    """
    Calculate planned_start_date (and custom_planned_end_date) for Production Plan FG items.

    Strategy per manufacturing type
    ─────────────────────────────────────────────────────────────────────────────
    In House
      • Backward-schedule from delivery_date using BOM production minutes,
        respecting shift hours, lunch break, and holiday list.
      • If the calculated start is in the past (allow_backdated OFF):
          – Clamp start to the nearest valid shift time (shift_start if before
            shift, lunch_end if in lunch, next-day shift_start if after shift).
          – Forward-schedule finish from that clamped start.
    Subcontract
      • Skipped here — handled by master_set_fg_dates_by_type (which also has
        supplier / lead-time data).
    No type set
      • Simple naive subtraction with shift-clamped backdating fallback.
    ─────────────────────────────────────────────────────────────────────────────

    Args:
        doc: Production Plan document
        method: Event method name (unused, required for hook signature)
    """
    del method  # Unused but required for hook signature
    # AVI
    if _skip_during_data_import():
        return
    # AVI

    if doc.get("get_items_from") != "Sales Order":
        return

    if not doc.get("po_items"):
        return

    combine_items = bool(doc.get("combine_items"))

    # Batch fetch all delivery dates and BOM operation times (1–2 queries total)
    delivery_cache = _batch_fetch_delivery_dates(doc, combine_items)
    bom_time_cache = _batch_fetch_bom_operations(doc)

    # Always shift-aware (510 net min/day fallback when shift not configured)
    shift_config = _get_effective_shift_config()

    for po_item in list(doc.get("po_items") or []):
        try:
            mfg_type = po_item.get("custom_manufacturing_type") or ""

            # Subcontract: let master_set_fg_dates_by_type handle start + end
            if mfg_type == "Subcontract":
                continue

            delivery_date = _get_delivery_date_from_cache(po_item, combine_items, delivery_cache)
            if not delivery_date:
                continue

            delivery_datetime = get_datetime(delivery_date)
            production_minutes = _calculate_production_minutes(
                po_item.bom_no, po_item.planned_qty, bom_time_cache
            )

            # ── PLANNED START DATE ──────────────────────────────────────────
            if mfg_type == "In House":
                # Shift-aware backward scheduling; falls back to shift-clamped
                # now_datetime() when the result would be in the past.
                planned_datetime = get_adjusted_inhouse_start_date(
                    delivery_datetime, production_minutes
                )
            else:
                # No manufacturing type: naive subtraction + backdating + clamp
                if production_minutes > 0:
                    planned_datetime = _subtract_minutes_from_datetime(
                        delivery_datetime, production_minutes
                    )
                else:
                    planned_datetime = delivery_datetime

                planned_datetime = _adjust_date_if_backdated(planned_datetime)
                if shift_config:
                    planned_datetime = clamp_to_current_shift(planned_datetime, shift_config)

            # ── PLANNED END DATE (forward schedule from start) ──────────────
            finish_datetime = recalculate_finish_date(
                planned_datetime, production_minutes, shift_config
            )

            po_item.planned_start_date = str(planned_datetime)
            po_item.custom_planned_end_date = str(finish_datetime)

        except Exception as e:
            frappe.log_error(
                message=f"Error calculating planned_start_date for {po_item.item_code}: {str(e)}",
                title="Production Plan Date Calculation",
            )
            if not po_item.planned_start_date:
                po_item.planned_start_date = str(now_datetime())


@frappe.whitelist()
def get_items_suppliers_batch(item_codes: str) -> dict:
    """
    Batch-fetch all subcontracting suppliers for a list of item codes.

    Called in parallel with get_production_plan_constraints when the
    Manage Dates dialog opens — one query instead of N per-item calls.

    Args:
        item_codes: JSON array string, e.g. '["ITEM-001", "ITEM-002"]'

    Returns:
        {item_code: [{supplier, lead_time_days, is_default}]}
        Sorted default-first within each item.
    """
    import json

    codes: list[str] = json.loads(item_codes) if isinstance(item_codes, str) else list(item_codes or [])
    if not codes:
        return {}

    rows = frappe.db.get_all(
        "Item Subcontracting Supplier",
        filters={"parent": ["in", codes]},
        fields=["parent", "supplier", "lead_time_days", "is_default"],
        order_by="is_default desc, supplier asc",
    )

    result: dict = {}
    for r in rows:
        item = r["parent"]
        if item not in result:
            result[item] = []
        result[item].append({
            "supplier":       r["supplier"],
            "lead_time_days": int(r["lead_time_days"] or 0),
            "is_default":     bool(r["is_default"]),
        })

    return result


@frappe.whitelist()
def get_production_plan_constraints() -> dict:
    """
    Returns all constraints needed by the Manage Dates dialog in a single API round-trip.

    Combines:
    - Manufacturing Settings (shift_wise scheduling, allow backdated)
    - Shift Type config (start/end times, lunch break)
    - Holiday dates for the shift's holiday list

    This collapses 3 sequential frappe.client calls on the JS side into one.
    """
    ms = frappe.db.get_value(
        "Manufacturing Settings",
        None,  # Singles doctype — no name filter needed
        ["enable_shift_wise_scheduling", "allow_backdated_planned_start_date"],
        as_dict=True,
    ) or {}

    shift_wise     = cint(ms.get("enable_shift_wise_scheduling")) == 1
    allow_backdate = cint(ms.get("allow_backdated_planned_start_date")) == 1

    # Reuse existing logic: resolves default_shift_type, caches, and builds the full config dict
    shift_config: dict | None = _get_effective_shift_config() if shift_wise else None

    holidays: list[str] = []
    if shift_config and shift_config.get("holiday_list"):
        raw = frappe.db.get_all(
            "Holiday",
            filters={"parent": shift_config["holiday_list"]},
            pluck="holiday_date",
        )
        holidays = [str(d) for d in raw]

    return {
        "shift_wise":     shift_wise,
        "allow_backdate": allow_backdate,
        "shift":          shift_config,
        "holidays":       holidays,
    }


@frappe.whitelist()
def recalculate_fg_end_date(
    planned_start_date: str,
    bom_no: str,
    planned_qty: float | str,
    manufacturing_type: str = "",
    item_code: str = "",
    supplier: str = "",
) -> dict[str, str]:
    """
    Recalculate custom_planned_end_date for a single FG row.

    Called by the Manage Dates dialog whenever the user changes
    planned_start_date or custom_manufacturing_type.

    In House    → forward-schedule using BOM operation minutes + shift config.
    Subcontract → start_date + default-supplier lead_time_days + GRN processing days,
                  holiday-adjusted (mirrors master_set_fg_dates_by_type logic).

    Args:
        planned_start_date: New start datetime string ("YYYY-MM-DD HH:MM:SS")
        bom_no:             BOM number (In House only)
        planned_qty:        Planned production quantity (In House only)
        manufacturing_type: "In House", "Subcontract", or ""
        item_code:          Item code (required for Subcontract lead-time lookup)

    Returns:
        {"custom_planned_end_date": "YYYY-MM-DD HH:MM:SS"}
    """
    start_dt     = get_datetime(planned_start_date)
    shift_config = _get_effective_shift_config()

    # ── Subcontract: lead_time + GRN days, holiday-adjusted ─────────────────
    if manufacturing_type == "Subcontract":
        lead_time = 0
        grn_days  = 0

        if item_code:
            # Use specific supplier's lead time if provided, else fall back to default
            filters = (
                {"parent": item_code, "supplier": supplier}
                if supplier
                else {"parent": item_code, "is_default": 1}
            )
            lead_time = int(
                frappe.db.get_value("Item Subcontracting Supplier", filters, "lead_time_days") or 0
            )
            grn_days = int(
                frappe.db.get_value("Item", item_code, "custom_expected_grn_processing_days") or 0
            )

        holiday_list = shift_config.get("holiday_list") if shift_config else None
        end_date     = getdate(add_days(getdate(start_dt), lead_time))
        end_date     = get_holiday_adjusted_date(end_date, grn_days, holiday_list)

        bkd_parts = [f"Lead: {lead_time}d"]
        if grn_days:
            bkd_parts.append(f"GRN: {grn_days}d")

        return {
            "custom_planned_end_date": str(_to_datetime(end_date)),
            "breakdown": " · ".join(bkd_parts),
        }

    # ── In House: forward-schedule using BOM operation minutes ───────────────
    qty: float = float(planned_qty or 0)

    bom_cache: dict[str, list[dict[str, Any]]] = {}
    if bom_no:
        operations = frappe.db.sql(
            """
            SELECT parent AS bom_no, time_in_mins, custom_batchsize, operation, idx
            FROM `tabBOM Operation`
            WHERE parent = %s
            ORDER BY idx
            """,
            (bom_no,),
            as_dict=True,
        )
        if operations:
            bom_cache[bom_no] = operations

    prod_mins = _calculate_production_minutes(bom_no, qty, bom_cache)
    end_dt    = recalculate_finish_date(start_dt, prod_mins, shift_config)
    hours     = round(prod_mins / 60, 1) if prod_mins else 0

    return {
        "custom_planned_end_date": str(end_dt),
        "breakdown": f"Prod: {hours}h" if hours else "",
    }
