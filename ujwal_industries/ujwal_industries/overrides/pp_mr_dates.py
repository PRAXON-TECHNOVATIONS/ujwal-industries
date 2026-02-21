# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""
MR (Material Request / mr_items) date management functions for Production Plan.
Handles backdating adjustment for MR items and propagation of raw-material
delays up the BOM chain (RM → SFG → FG, or RM → FG directly).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, getdate, get_datetime, now_datetime

from .pp_utils import (
    _skip_during_data_import,
    _get_allow_backdated_setting,
    _get_effective_shift_config,
    _get_holiday_set,
    _prev_working_date,
    _to_datetime,
    _as_timedelta,
    get_holiday_adjusted_date,
    _batch_fetch_bom_operations,
    _batch_fetch_subassembly_bom_operations,
    _calculate_production_minutes,
    _get_supplier_lead_time,
    shift_aware_forward_schedule,
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
    # AVI
    if _skip_during_data_import():
        return
    # AVI

    if _get_allow_backdated_setting():
        return

    today = getdate()
    mr_adjustments: list[dict[str, Any]] = []

    # Batch-fetch GRN processing days for all MR items (one query)
    mr_rows = doc.get("mr_items") or []
    mr_item_codes = list(set(r.item_code for r in mr_rows if r.item_code))
    grn_days_map: dict[str, int] = {}
    if mr_item_codes:
        grn_raw = frappe.db.sql("""
            SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days
            FROM `tabItem` WHERE name IN %(items)s
        """, {"items": mr_item_codes}, as_dict=True)
        grn_days_map = {d.name: int(d.grn_days) for d in grn_raw}

    # Holiday list from Manufacturing Settings → default_shift_type
    holiday_list = _get_effective_shift_config().get("holiday_list")

    # --- Step 1: Adjust backdated mr_items ---
    for row in mr_rows:
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

        grn_days = grn_days_map.get(row.item_code, 0)

        original_schedule_date = getdate(row.schedule_date) if row.get("schedule_date") else today

        # receive_date = today + lead_time (all calendar days, no holiday skip)
        # schedule_date = receive_date + grn_days (working/holiday-aware days)
        receive_date = add_days(today, lead_time)
        new_schedule_date = get_holiday_adjusted_date(receive_date, grn_days, holiday_list)

        row.custom_start_date = _to_datetime(today)
        row.schedule_date = _to_datetime(new_schedule_date)

        mr_adjustments.append({
            "idx": row.idx,
            "item_code": row.item_code,
            "lead_time": lead_time,
            "grn_days": grn_days,
            "original_start": start_date,
            "original_schedule": original_schedule_date,
            "new_start": today,
            "new_schedule": new_schedule_date,
        })

    # --- Step 2: Show consolidated MR adjustment message (only if adjustments made this save) ---
    if mr_adjustments:
        max_mr_schedule = max(a["new_schedule"] for a in mr_adjustments)
        details = "<br>".join([
            "Row #{0} <b>{1}</b> — Start: <b>{2}</b> → <b>{3}</b> | Schedule: <b>{4}</b> → <b>{5}</b> (lead time: {6}d{7})".format(
                a["idx"],
                a["item_code"],
                frappe.format(a["original_start"], "Date"),
                frappe.format(a["new_start"], "Date"),
                frappe.format(a["original_schedule"], "Date"),
                frappe.format(a["new_schedule"], "Date"),
                a["lead_time"],
                f", GRN: {a['grn_days']}d" if a["grn_days"] else "",
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

    Step A: For each SFG whose BOM directly uses a delayed RM, recompute start/end from
    scratch — NOT by shifting old dates by calendar days. Different months can have
    different holiday densities (e.g. the fiscal-year holiday list may cover Sat/Sun
    through March but have NO April entries, making April fully working).

    Step B: Propagate upward through the BOM chain using the authoritative time source:
      - Subcontract SFGs: lead_time_days + grn_days (holiday-adjusted), from Item master
      - In House SFGs:    shift_aware_forward_schedule using BOM operation minutes
    """
    _shift_cfg     = _get_effective_shift_config()
    shift_start_td = _as_timedelta(_shift_cfg.get("start_time")) or timedelta(hours=10)
    holiday_list   = _shift_cfg.get("holiday_list")
    holidays       = _get_holiday_set(holiday_list)
    sfg_bom_cache  = _batch_fetch_subassembly_bom_operations(doc)

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

    # bom_no → max delayed RM schedule_date (date object)
    bom_to_max_rm_schedule: dict[str, Any] = {}
    for link in bom_item_links:
        rm_sched = adjusted_rm_schedules[link.item_code]
        if link.bom_no not in bom_to_max_rm_schedule or rm_sched > bom_to_max_rm_schedule[link.bom_no]:
            bom_to_max_rm_schedule[link.bom_no] = rm_sched

    if not bom_to_max_rm_schedule:
        return

    # Batch-fetch GRN processing days for Subcontract SFGs
    subcontract_items = list(set(
        row.production_item for row in doc.sub_assembly_items
        if row.get("type_of_manufacturing") == "Subcontract" and row.production_item
    ))
    grn_days_map: dict[str, int] = {}
    if subcontract_items:
        grn_raw = frappe.db.sql(
            "SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days "
            "FROM `tabItem` WHERE name IN %(items)s",
            {"items": subcontract_items},
            as_dict=True,
        )
        grn_days_map = {d.name: int(d.grn_days) for d in grn_raw}

    # Build SFG map.
    # Key: (production_plan_item, production_item) — unique per BOM chain.
    # Each entry stores the authoritative time parameters (time_type / lead_time /
    # grn_days / prod_mins) so Step B cascade mirrors pp_sfg_dates.py Pass 2 exactly.
    sfg_map: dict[tuple[str, str], dict[str, Any]] = {}
    for row in doc.sub_assembly_items:
        if not row.schedule_date or not row.custom_schedule_end_date:
            continue
        schedule_dt = get_datetime(row.schedule_date)
        end_dt      = get_datetime(row.custom_schedule_end_date)
        chain_id    = row.production_plan_item or ""

        is_subcontract = row.get("type_of_manufacturing") == "Subcontract"
        if is_subcontract:
            lead_time = (
                _get_supplier_lead_time(row.production_item, row.supplier, doc.company)
                if row.get("supplier") else 0
            )
            grn_days  = grn_days_map.get(row.production_item, 0)
            prod_mins = 0.0
            time_type = "lead_time"
        else:
            lead_time = 0
            grn_days  = 0
            prod_mins = _calculate_production_minutes(row.bom_no, row.qty, sfg_bom_cache)
            time_type = "production_minutes"

        sfg_map[(chain_id, row.production_item)] = {
            "row":                  row,
            "chain_id":             chain_id,
            "production_item":      row.production_item,
            "schedule_dt":          schedule_dt,
            "end_dt":               end_dt,
            "duration_td":          end_dt - schedule_dt,  # fallback only
            "parent_item_code":     row.parent_item_code,
            "bom_no":               row.bom_no,
            "original_schedule_dt": schedule_dt,
            "original_end_dt":      end_dt,
            "time_type":            time_type,
            "lead_time":            lead_time,
            "grn_days":             grn_days,
            "prod_mins":            prod_mins,
        }

    # ── Step A ───────────────────────────────────────────────────────────────
    # Push SFGs whose BOM directly contains a delayed RM.
    # Use authoritative scheduling (not calendar-day shifting of old dates).
    sfg_changed = False
    for key, data in sfg_map.items():
        if data["bom_no"] not in bom_to_max_rm_schedule:
            continue
        rm_max_date = bom_to_max_rm_schedule[data["bom_no"]]   # date
        if rm_max_date <= getdate(data["schedule_dt"]):
            continue

        # First working day on-or-after rm_max_date → shift_start time
        new_start_date = rm_max_date
        while new_start_date in holidays:
            new_start_date += timedelta(days=1)
        new_schedule_dt: Any = datetime.combine(new_start_date, datetime.min.time()) + shift_start_td

        # New end: authoritative per time_type
        if data["time_type"] == "lead_time":
            lt      = data["lead_time"]
            grn     = data["grn_days"]
            end_raw = getdate(add_days(new_start_date, lt))
            end_adj = get_holiday_adjusted_date(end_raw, grn, holiday_list)
            new_end_dt: Any = datetime.combine(getdate(end_adj), datetime.min.time()) + shift_start_td
        elif data["prod_mins"] > 0:
            new_end_dt = shift_aware_forward_schedule(new_schedule_dt, data["prod_mins"], _shift_cfg)
        else:
            new_end_dt = new_schedule_dt + data["duration_td"]

        data["schedule_dt"] = new_schedule_dt
        data["end_dt"]      = new_end_dt
        sfg_changed = True

    if not sfg_changed:
        return

    # ── Step B ───────────────────────────────────────────────────────────────
    # Bottom-up cascade: if child end_dt > parent schedule_dt, push the parent.
    # Subcontract parent → lead_time + grn_days (holiday-adjusted calendar days).
    # In House parent   → shift_aware_forward_schedule using BOM prod_mins.
    for _iter in range(10):
        changes_made = False
        for key, data in sfg_map.items():
            parent_key  = (data["chain_id"], data["parent_item_code"])
            parent_data = sfg_map.get(parent_key)
            if not parent_data:
                continue
            if data["end_dt"] <= parent_data["schedule_dt"]:
                continue

            parent_data["schedule_dt"] = data["end_dt"]

            if parent_data["time_type"] == "lead_time":
                lt      = parent_data["lead_time"]
                grn     = parent_data["grn_days"]
                end_raw = getdate(add_days(getdate(data["end_dt"]), lt))
                end_adj = get_holiday_adjusted_date(end_raw, grn, holiday_list)
                parent_data["end_dt"] = (
                    datetime.combine(getdate(end_adj), datetime.min.time()) + shift_start_td
                )
            elif parent_data["prod_mins"] > 0:
                parent_data["end_dt"] = shift_aware_forward_schedule(
                    data["end_dt"], parent_data["prod_mins"], _shift_cfg
                )
            else:
                parent_data["end_dt"] = data["end_dt"] + parent_data["duration_td"]

            changes_made = True
        if not changes_made:
            break

    # Step C: Apply updated datetimes to SFG rows + collect changes
    sfg_adjustments: list[dict[str, Any]] = []
    for key, data in sfg_map.items():
        if data["schedule_dt"] != data["original_schedule_dt"] or data["end_dt"] != data["original_end_dt"]:
            data["row"].schedule_date = str(data["schedule_dt"])
            data["row"].custom_schedule_end_date = str(data["end_dt"])
            sfg_adjustments.append({
                "production_item": data["production_item"],
                "original_schedule": getdate(data["original_schedule_dt"]),
                "new_schedule": getdate(data["schedule_dt"]),
                "original_end": getdate(data["original_end_dt"]),
                "new_end": getdate(data["end_dt"]),
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

    fg_bom_cache = _batch_fetch_bom_operations(doc)
    shift_config = _get_effective_shift_config()

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
            start_dt = get_datetime(po_item.planned_start_date)
            fg_prod_mins = _calculate_production_minutes(po_item.bom_no, po_item.planned_qty, fg_bom_cache)
            if fg_prod_mins > 0:
                po_item.custom_planned_end_date = str(
                    shift_aware_forward_schedule(start_dt, fg_prod_mins, shift_config)
                )

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
    fg_bom_cache = _batch_fetch_bom_operations(doc)
    shift_config = _get_effective_shift_config()

    # Find max end_datetime per FG from its direct SFG children (datetime for precision)
    fg_max_end: dict[str, Any] = {}
    for row in doc.sub_assembly_items:
        if row.parent_item_code not in fg_item_codes or not row.custom_schedule_end_date:
            continue
        sfg_end = get_datetime(row.custom_schedule_end_date)
        if row.parent_item_code not in fg_max_end or sfg_end > fg_max_end[row.parent_item_code]:
            fg_max_end[row.parent_item_code] = sfg_end

    # Push FG where needed
    for po_item in doc.po_items:
        if po_item.item_code not in fg_max_end:
            continue
        max_sfg_end = fg_max_end[po_item.item_code]
        if max_sfg_end > get_datetime(po_item.planned_start_date):
            fg_adjustments.append({
                "item_code": po_item.item_code,
                "original": getdate(po_item.planned_start_date),
                "new": getdate(max_sfg_end),
            })
            po_item.planned_start_date = str(max_sfg_end)
            fg_prod_mins = _calculate_production_minutes(po_item.bom_no, po_item.planned_qty, fg_bom_cache)
            if fg_prod_mins > 0:
                po_item.custom_planned_end_date = str(
                    shift_aware_forward_schedule(max_sfg_end, fg_prod_mins, shift_config)
                )

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


@frappe.whitelist()
def recalculate_mr_schedule_date(
    production_plan_name: str,
    mr_row_name: str,
    new_start_date: str,
    supplier_override: str | None = None,
) -> dict[str, Any]:
    """
    Given a new custom_start_date for a MR row, compute the resulting schedule_date.

    Both lead_time_days and grn_days are advanced in WORKING days (skipping holidays/weekends
    from the effective shift config's holiday list).

    Args:
        supplier_override: When provided, use this supplier for lead_time lookup instead
            of the saved row.custom_supplier (needed when user changes supplier in dialog
            before saving).
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)
    row = next((r for r in (doc.get("mr_items") or []) if r.name == mr_row_name), None)
    if not row:
        return {}

    start_d      = getdate(new_start_date)
    holiday_list = _get_effective_shift_config().get("holiday_list")

    # Use supplier_override from dialog if provided; fall back to saved row value
    supplier  = (supplier_override or "").strip() or row.get("custom_supplier") or ""
    lead_time = 0
    if supplier:
        lt = frappe.db.get_value(
            "Item Subcontracting Supplier",
            {"parent": row.item_code, "supplier": supplier, "company": doc.company},
            "lead_time_days",
        )
        lead_time = int(lt or 0)

    grn_days = int(
        frappe.db.get_value("Item", row.item_code, "custom_expected_grn_processing_days") or 0
    )

    # Advance in WORKING days — skips Sat/Sun and any holidays in the holiday list
    receive_date  = get_holiday_adjusted_date(start_d, lead_time, holiday_list)
    schedule_date = get_holiday_adjusted_date(receive_date, grn_days, holiday_list)

    return {"schedule_date": str(schedule_date)}


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

    # Batch-fetch GRN processing days for all raw materials (one query)
    grn_raw = frappe.db.sql("""
        SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days
        FROM `tabItem` WHERE name IN %(items)s
    """, {"items": raw_material_items}, as_dict=True)
    grn_days_map: dict[str, int] = {d.name: int(d.grn_days) for d in grn_raw}

    # Holiday list from Manufacturing Settings → default_shift_type
    shift_config = _get_effective_shift_config()
    holidays_set = _get_holiday_set(shift_config.get("holiday_list"))

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
        grn_days = grn_days_map.get(item_code, 0)
        supplier_name = supplier_info.supplier

        # Step backward from base_date:
        #   1. subtract grn_days as working/holiday-aware days → receive_date
        #   2. subtract lead_time as plain calendar days → custom_start_date (when to order)
        # schedule_date stays as base_date (when the SFG/FG needs the material)
        receive_date = getdate(lowest_base_date)
        for _ in range(grn_days):
            receive_date = _prev_working_date(receive_date, holidays_set)

        custom_start_date = add_days(receive_date, -lead_time)

        results[item_code] = {
            "custom_start_date": str(_to_datetime(custom_start_date)),
            "schedule_date": str(lowest_base_date),
            "custom_supplier": supplier_name
        }

    return results


@frappe.whitelist()
def recalculate_mr_dates_from_sfg(
    production_plan_name: str,
    sfg_dates_data: list[dict[str, Any]] | str,
    po_item_name: str | None = None,
) -> dict[str, dict[str, str]]:
    """
    Given the current in-dialog SFG schedule_dates (may differ from DB),
    recalculate all MR item custom_start_date and schedule_date.

    Used by the Manage Dates dialog: after FG→SFG or SFG→upward cascades update
    SFG inputs in Steps 1/2, this recomputes Step 3 (MR) dates automatically.

    Args:
        production_plan_name: Name of Production Plan.
        sfg_dates_data: [{name, schedule_date}, ...] — current dialog values.
        po_item_name: If provided, restrict recalculation to SFGs and MR rows
            belonging to this FG chain only (filters by production_plan_item and
            matching sales_order).

    Returns:
        {mr_row_name: {custom_start_date, schedule_date}}
    """
    import json as _json

    if isinstance(sfg_dates_data, str):
        sfg_dates_data = _json.loads(sfg_dates_data)

    doc = frappe.get_doc("Production Plan", production_plan_name)
    mr_rows = doc.get("mr_items") or []
    if not mr_rows:
        return {}

    # ── Chain-scoped filter (when caller provides po_item_name) ──────────
    chain_sfg_names: set[str] | None = None
    if po_item_name:
        # Find the sales_order for this FG chain
        chain_so: str | None = None
        for po_item in (doc.po_items or []):
            if po_item.name == po_item_name:
                chain_so = po_item.sales_order or None
                break

        # Restrict sfg_dates_data to SFGs belonging to this chain
        chain_sfg_names = {
            r.name for r in (doc.sub_assembly_items or [])
            if r.production_plan_item == po_item_name
        }
        sfg_dates_data = [item for item in sfg_dates_data if item.get("name") in chain_sfg_names]

        # Restrict MR rows to matching sales_order
        if chain_so:
            mr_rows = [r for r in mr_rows if r.sales_order == chain_so]
    # ─────────────────────────────────────────────────────────────────────

    raw_material_items = list(set(r.item_code for r in mr_rows if r.item_code))
    if not raw_material_items:
        return {}

    # Build sfg_row_name → schedule_date override from dialog
    sfg_override: dict[str, Any] = {
        item["name"]: item["schedule_date"]
        for item in sfg_dates_data
        if item.get("name") and item.get("schedule_date")
    }

    # Build production_item → {bom_no, schedule_date} using dialog overrides.
    # When chain_sfg_names is set, restrict to this chain's SFG rows only —
    # sibling chains share the same production_items but have different schedule_dates,
    # and taking the global minimum would select the wrong (sibling) chain's date.
    _sfg_rows_for_map = (
        [r for r in (doc.sub_assembly_items or []) if r.name in chain_sfg_names]
        if chain_sfg_names is not None
        else (doc.sub_assembly_items or [])
    )
    sfg_bom_map: dict[str, dict[str, Any]] = {}
    for row in _sfg_rows_for_map:
        if not row.bom_no or not row.production_item:
            continue
        schedule_date = sfg_override.get(row.name) or row.schedule_date
        if not schedule_date:
            continue
        existing = sfg_bom_map.get(row.production_item)
        # Use earliest schedule_date within the chain for the same production_item
        if not existing or get_datetime(schedule_date) < get_datetime(existing["schedule_date"]):
            sfg_bom_map[row.production_item] = {"bom_no": row.bom_no, "schedule_date": schedule_date}

    if not sfg_bom_map:
        return {}

    sfg_boms = list(set(info["bom_no"] for info in sfg_bom_map.values()))
    bom_items_data = frappe.db.sql(
        """SELECT parent as bom_no, item_code FROM `tabBOM Item`
           WHERE parent IN %(bom_nos)s AND item_code IN %(raw_items)s""",
        {"bom_nos": sfg_boms, "raw_items": raw_material_items},
        as_dict=True,
    )

    # bom_no → [raw_material_item_codes]
    bom_to_raw: dict[str, list[str]] = {}
    for row in bom_items_data:
        bom_to_raw.setdefault(row.bom_no, []).append(row.item_code)

    # raw_material → [base_datetimes from SFG schedule_dates]
    raw_to_base: dict[str, list[Any]] = {}
    for sfg_item, info in sfg_bom_map.items():
        for raw_item in bom_to_raw.get(info["bom_no"], []):
            raw_to_base.setdefault(raw_item, []).append(get_datetime(info["schedule_date"]))

    if not raw_to_base:
        return {}

    # Batch fetch default supplier and GRN days
    supplier_data = frappe.db.sql(
        """SELECT parent as item_code, supplier, lead_time_days
           FROM `tabItem Subcontracting Supplier`
           WHERE parent IN %(items)s AND company = %(company)s AND is_default = 1""",
        {"items": raw_material_items, "company": doc.company},
        as_dict=True,
    )
    supplier_map = {s.item_code: s for s in supplier_data}

    grn_raw = frappe.db.sql(
        "SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days "
        "FROM `tabItem` WHERE name IN %(items)s",
        {"items": raw_material_items},
        as_dict=True,
    )
    grn_days_map: dict[str, int] = {d.name: int(d.grn_days) for d in grn_raw}

    shift_config = _get_effective_shift_config()
    holidays_set = _get_holiday_set(shift_config.get("holiday_list"))

    # Compute per item_code
    item_results: dict[str, dict[str, str]] = {}
    for item_code in raw_material_items:
        if item_code not in raw_to_base:
            continue
        lowest_base = min(raw_to_base[item_code])
        sup = supplier_map.get(item_code)
        if not sup or not sup.supplier:
            continue
        lead_time = int(sup.lead_time_days or 0)
        grn_days = grn_days_map.get(item_code, 0)
        receive_date = getdate(lowest_base)
        for _ in range(grn_days):
            receive_date = _prev_working_date(receive_date, holidays_set)
        custom_start_date = add_days(receive_date, -lead_time)
        item_results[item_code] = {
            "custom_start_date": str(_to_datetime(custom_start_date)),
            "schedule_date":     str(lowest_base.date() if hasattr(lowest_base, "date") else lowest_base),
        }

    # Map item_code → mr_row_name for dialog input targeting
    return {
        row.name: item_results[row.item_code]
        for row in mr_rows
        if row.item_code in item_results
    }


@frappe.whitelist()
def propagate_mr_schedule_to_sfg_fg(
    production_plan_name: str,
    mr_schedule_dates: dict[str, Any] | str,
    sfg_dates_override: list[dict[str, Any]] | str | None = None,
    fg_dates_override: list[dict[str, Any]] | str | None = None,
    mr_row_name_filter: str | None = None,
) -> dict[str, Any]:
    """
    Given updated MR schedule_dates from the dialog, compute the cascaded SFG
    and FG dates — without touching the database.

    Mirrors the before_save hook logic (_propagate_rm_delays_to_sfg_and_fg +
    _enforce_fg_waits_for_sfg) but operates on an in-memory copy of the doc so
    the dialog can show live previews before the user clicks Apply.

    Args:
        production_plan_name: Name of Production Plan.
        mr_schedule_dates: {item_code: schedule_date_str} — current MR dates from dialog.
        sfg_dates_override: [{name, schedule_date, custom_schedule_end_date}, ...] — dialog SFG state.
        fg_dates_override:  [{name, planned_start_date, custom_planned_end_date}, ...] — dialog FG state.
        mr_row_name_filter: When provided, restrict cascade to only the SFG/FG chain that
            belongs to this MR row's sales_order (chain isolation — prevents sibling chains
            from being cascaded when only one row changed).

    Returns:
        {sfg_updates: {row_name: {schedule_date, custom_schedule_end_date}},
         fg_updates:  {row_name: {planned_start_date, custom_planned_end_date}}}
    """
    import json as _json

    if isinstance(mr_schedule_dates, str):
        mr_schedule_dates = _json.loads(mr_schedule_dates)
    if isinstance(sfg_dates_override, str):
        sfg_dates_override = _json.loads(sfg_dates_override) if sfg_dates_override else []
    if isinstance(fg_dates_override, str):
        fg_dates_override = _json.loads(fg_dates_override) if fg_dates_override else []

    adjusted_rm_schedules: dict[str, Any] = {
        item_code: getdate(sched_date)
        for item_code, sched_date in (mr_schedule_dates or {}).items()
        if sched_date
    }
    if not adjusted_rm_schedules:
        return {"sfg_updates": {}, "fg_updates": {}}

    doc = frappe.get_doc("Production Plan", production_plan_name)

    # Apply current dialog state so the cascade starts from the right baseline
    if sfg_dates_override:
        sfg_ov_map = {item["name"]: item for item in sfg_dates_override if item.get("name")}
        for row in (doc.sub_assembly_items or []):
            ov = sfg_ov_map.get(row.name)
            if not ov:
                continue
            if ov.get("schedule_date"):
                row.schedule_date = ov["schedule_date"]
            if ov.get("custom_schedule_end_date"):
                row.custom_schedule_end_date = ov["custom_schedule_end_date"]

    if fg_dates_override:
        fg_ov_map = {item["name"]: item for item in fg_dates_override if item.get("name")}
        for row in (doc.po_items or []):
            ov = fg_ov_map.get(row.name)
            if not ov:
                continue
            if ov.get("planned_start_date"):
                row.planned_start_date = ov["planned_start_date"]
            if ov.get("custom_planned_end_date"):
                row.custom_planned_end_date = ov["custom_planned_end_date"]

    # ── Chain isolation ───────────────────────────────────────────────────────
    # When a single MR row changed, restrict cascade to that row's SO chain only.
    # This prevents sibling chains (same raw material, different sales_order) from
    # being unnecessarily pushed forward.
    _original_sfg = None
    _original_po  = None
    if mr_row_name_filter:
        mr_row = next((r for r in (doc.mr_items or []) if r.name == mr_row_name_filter), None)
        chain_so = (mr_row.sales_order or None) if mr_row else None
        if chain_so:
            chain_po_names = {r.name for r in (doc.po_items or []) if r.sales_order == chain_so}
            _original_sfg = doc.sub_assembly_items
            _original_po  = doc.po_items
            # Temporarily narrow doc to only this chain's rows
            doc.sub_assembly_items = [r for r in doc.sub_assembly_items if r.production_plan_item in chain_po_names]
            doc.po_items = [r for r in doc.po_items if r.sales_order == chain_so]
    # ─────────────────────────────────────────────────────────────────────────

    # Capture baseline (post-override, post-filter) to detect what changed
    sfg_before: dict[str, dict[str, Any]] = {
        row.name: {
            "schedule_date":            str(row.schedule_date or ""),
            "custom_schedule_end_date": str(row.custom_schedule_end_date or ""),
        }
        for row in (doc.sub_assembly_items or [])
    }
    fg_before: dict[str, dict[str, Any]] = {
        row.name: {
            "planned_start_date":    str(row.planned_start_date or ""),
            "custom_planned_end_date": str(row.custom_planned_end_date or ""),
        }
        for row in (doc.po_items or [])
    }

    # Run the same cascade logic as the before_save hook (in-memory only).
    # Snapshot message_log so any frappe.msgprint calls inside the helpers
    # don't surface as server_messages in the dialog's JSON response.
    _log_snapshot = len(frappe.local.message_log)
    try:
        if doc.get("sub_assembly_items"):
            _propagate_rm_delays_to_sfg_and_fg(doc, adjusted_rm_schedules)
        else:
            _propagate_rm_delays_to_fg(doc, adjusted_rm_schedules)

        if doc.get("sub_assembly_items"):
            _enforce_fg_waits_for_sfg(doc)
    finally:
        # Discard any messages appended by the preview cascade (non-save context)
        del frappe.local.message_log[_log_snapshot:]

    # Restore full lists after chain-scoped cascade (row objects were mutated in-place)
    if _original_sfg is not None:
        doc.sub_assembly_items = _original_sfg
    if _original_po is not None:
        doc.po_items = _original_po

    # Collect rows that actually changed.
    # Only emit rows that were in scope during the cascade (those in sfg_before/fg_before).
    # Rows that weren't in scope (sibling chains) are absent from sfg_before — skip them
    # to avoid false positives caused by the sfg_dates_override applied to all rows.
    sfg_updates: dict[str, dict[str, str]] = {}
    for row in (doc.sub_assembly_items or []):
        before = sfg_before.get(row.name)
        if before is None:
            continue  # not in the cascade scope — skip
        new_sd  = str(row.schedule_date or "")
        new_end = str(row.custom_schedule_end_date or "")
        if new_sd != before.get("schedule_date") or new_end != before.get("custom_schedule_end_date"):
            sfg_updates[row.name] = {
                "schedule_date":            new_sd,
                "custom_schedule_end_date": new_end,
            }

    fg_updates: dict[str, dict[str, str]] = {}
    for row in (doc.po_items or []):
        before = fg_before.get(row.name)
        if before is None:
            continue  # not in the cascade scope — skip
        new_ps  = str(row.planned_start_date or "")
        new_end = str(row.custom_planned_end_date or "")
        if new_ps != before.get("planned_start_date") or new_end != before.get("custom_planned_end_date"):
            fg_updates[row.name] = {
                "planned_start_date":    new_ps,
                "custom_planned_end_date": new_end,
            }

    return {"sfg_updates": sfg_updates, "fg_updates": fg_updates}


@frappe.whitelist()
def save_managed_dates(
    production_plan_name: str,
    po_items_data: list[dict[str, Any]] | str,
    sfg_data: list[dict[str, Any]] | str,
    mr_data: list[dict[str, Any]] | str,
) -> dict[str, str]:
    """
    Directly persist all date/type/supplier changes from the Manage Dates dialog
    without triggering any before_save or validate hooks.

    Uses frappe.db.set_value on each child-table row so that hooks like
    set_planned_start_dates, set_subcontracting_suppliers, master_set_fg_dates_by_type,
    and adjust_mr_items_and_propagate are completely bypassed — the manually chosen
    dates are stored exactly as the user set them in the dialog.
    """
    import json as _json

    if isinstance(po_items_data, str):
        po_items_data = _json.loads(po_items_data)
    if isinstance(sfg_data, str):
        sfg_data = _json.loads(sfg_data)
    if isinstance(mr_data, str):
        mr_data = _json.loads(mr_data)

    # ── FG po_items ────────────────────────────────────────────────────────
    _FG_FIELDS = {"planned_start_date", "custom_planned_end_date",
                  "custom_manufacturing_type", "custom_supplier"}
    for item in (po_items_data or []):
        updates = {k: v for k, v in item.items() if k in _FG_FIELDS and v is not None}
        if updates:
            frappe.db.set_value("Production Plan Item", item["name"], updates,
                                update_modified=False)

    # ── SFG sub_assembly_items ─────────────────────────────────────────────
    _SFG_FIELDS = {"schedule_date", "custom_schedule_end_date",
                   "type_of_manufacturing", "supplier"}
    for item in (sfg_data or []):
        updates = {k: v for k, v in item.items() if k in _SFG_FIELDS and v is not None}
        if updates:
            frappe.db.set_value("Production Plan Sub Assembly Item", item["name"], updates,
                                update_modified=False)

    # ── MR mr_items ────────────────────────────────────────────────────────
    _MR_FIELDS = {"custom_start_date", "schedule_date", "custom_supplier"}
    for item in (mr_data or []):
        updates = {k: v for k, v in item.items() if k in _MR_FIELDS and v is not None}
        if updates:
            frappe.db.set_value("Material Request Plan Item", item["name"], updates,
                                update_modified=False)

    # Mark as manually managed — skips all automatic date hooks on next save/submit
    frappe.db.set_value(
        "Production Plan", production_plan_name,
        {"custom_skip_date_calculation": 1, "modified": now_datetime()},
        update_modified=False,
    )
    frappe.db.commit()
    return {"status": "ok"}


@frappe.whitelist()
def get_pp_importer_data(production_plan_name: str) -> dict[str, list[dict]]:
    """
    Return the FG, SFG, and MR rows of a Production Plan for the importer spreadsheet.
    Only the fields the importer needs are fetched — keeps the payload small.
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)

    # Production Plan Item has no item_name field — only item_code
    po_items = [
        {
            "name":                      row.name,
            "item_code":                 row.item_code or "",
            "sales_order":               row.sales_order or "",
            "planned_qty":               row.planned_qty or 0,
            "bom_no":                    row.bom_no or "",
            "planned_start_date":        str(row.planned_start_date or ""),
            "custom_planned_end_date":   str(row.custom_planned_end_date or ""),
            "custom_manufacturing_type": row.custom_manufacturing_type or "",
            "custom_supplier":           row.custom_supplier or "",
        }
        for row in (doc.po_items or [])
    ]

    sfg_items = [
        {
            "name":                     row.name,
            "production_item":          row.production_item or "",
            "item_name":                row.item_name or "",
            "bom_no":                   row.bom_no or "",
            "qty":                      row.qty or 0,
            "production_plan_item":     row.production_plan_item or "",
            "schedule_date":            str(row.schedule_date or ""),
            "custom_schedule_end_date": str(row.custom_schedule_end_date or ""),
            "type_of_manufacturing":    row.type_of_manufacturing or "",
            "supplier":                 row.supplier or "",
            "parent_item_code":         row.parent_item_code or "",
        }
        for row in (doc.sub_assembly_items or [])
    ]

    # Material Request Plan Item — DB field is `quantity` (not `qty`)
    mr_items = [
        {
            "name":              row.name,
            "item_code":         row.item_code or "",
            "item_name":         row.item_name or "",
            "quantity":          row.quantity or 0,
            "sales_order":       row.sales_order or "",
            "custom_start_date": str(row.custom_start_date or ""),
            "schedule_date":     str(row.schedule_date or ""),
            "custom_supplier":   row.custom_supplier or "",
        }
        for row in (doc.mr_items or [])
    ]

    return {
        "po_items":  po_items,
        "sfg_items": sfg_items,
        "mr_items":  mr_items,
        "docstatus": doc.docstatus,   # 0=Draft, 1=Submitted, 2=Cancelled
    }


@frappe.whitelist()
def get_item_suppliers(item_codes: list | str) -> dict:
    """
    Return all subcontracting suppliers per item code for the importer dropdowns.
    Returns: { item_code: ["Supplier A", "Supplier B", ...] }
    """
    import json as _json

    if isinstance(item_codes, str):
        item_codes = _json.loads(item_codes)
    if not item_codes:
        return {}

    rows = frappe.db.sql(
        """
        SELECT parent AS item_code, supplier
        FROM `tabItem Subcontracting Supplier`
        WHERE parent IN %(items)s
        ORDER BY is_default DESC, supplier ASC
        """,
        {"items": item_codes},
        as_dict=True,
    )
    result: dict = {}
    for row in rows:
        result.setdefault(row.item_code, []).append(row.supplier)
    return result


@frappe.whitelist()
def parse_pp_excel(file_url: str) -> dict[str, dict]:
    """
    Parse a Production Plan Data Export Excel file and return data grouped by PP name.

    The Excel is the standard ERPNext Data Export format for Production Plan:
    - Single sheet, first row = headers
    - PP ID only on the first row of each PP group; remaining rows have None in col 0
    - Child table groups: "Assembly Items" (FG), "Sub Assembly Items" (SFG), "Raw Materials" (MR)

    Returns:
        { "MFG-PP-2026-00005": { "po_items": [...], "sfg_items": [...], "mr_items": [...] }, ... }
    """
    import os
    import openpyxl

    # ── Resolve physical path ──────────────────────────────────────────────
    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_path = file_doc.get_full_path()

    if not os.path.exists(file_path):
        frappe.throw(f"File not found: {file_path}")

    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    # ── Build column-index map from header row ─────────────────────────────
    headers = [str(c.value or "").strip() for c in ws[1]]
    col = {h: i for i, h in enumerate(headers)}

    def _get(row: tuple, header: str):
        idx = col.get(header)
        return row[idx] if idx is not None and idx < len(row) else None

    def _str(v) -> str:
        if v is None:
            return ""
        if hasattr(v, "strftime"):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return str(v).strip()

    # ── Parse rows ─────────────────────────────────────────────────────────
    pp_data: dict[str, dict] = {}
    current_pp: str | None = None

    for row in ws.iter_rows(min_row=2, values_only=True):
        # A non-None value in column 0 means a new PP starts
        pp_id = row[0]
        if pp_id:
            current_pp = str(pp_id).strip()
            if current_pp not in pp_data:
                pp_data[current_pp] = {
                    "po_items":  [],
                    "sfg_items": [],
                    "mr_items":  [],
                    "_fg_seen":  set(),
                    "_sfg_seen": set(),
                    "_mr_seen":  set(),
                }

        if not current_pp:
            continue

        bucket = pp_data[current_pp]

        # ── FG row (Assembly Items) ────────────────────────────────────────
        fg_id = _get(row, "ID (Assembly Items)")
        if fg_id and fg_id not in bucket["_fg_seen"]:
            bucket["_fg_seen"].add(fg_id)
            bucket["po_items"].append({
                "name":                      str(fg_id),
                "item_code":                 _str(_get(row, "Item Code (Assembly Items)")),
                "sales_order":               _str(_get(row, "Sales Order (Assembly Items)")),
                "planned_qty":               _get(row, "Planned Qty (Assembly Items)") or 0,
                "planned_start_date":        _str(_get(row, "Planned Start Date (Assembly Items)")),
                "custom_planned_end_date":   _str(_get(row, "Planned End Date (Assembly Items)")),
                "custom_manufacturing_type": _str(_get(row, "Manufacturing Type (Assembly Items)")),
                "custom_supplier":           _str(_get(row, "Supplier (Assembly Items)")),
            })

        # ── SFG row (Sub Assembly Items) ───────────────────────────────────
        sfg_id = _get(row, "ID (Sub Assembly Items)")
        if sfg_id and sfg_id not in bucket["_sfg_seen"]:
            bucket["_sfg_seen"].add(sfg_id)
            bucket["sfg_items"].append({
                "name":                     str(sfg_id),
                "production_item":          _str(_get(row, "Sub Assembly Item Code (Sub Assembly Items)")),
                "item_name":                _str(_get(row, "Item Name (Sub Assembly Items)")),
                "bom_no":                   _str(_get(row, "Bom No (Sub Assembly Items)")),
                "qty":                      _get(row, "Required Qty (Sub Assembly Items)") or 0,
                "schedule_date":            _str(_get(row, "Schedule Date (Sub Assembly Items)")),
                "custom_schedule_end_date": _str(_get(row, "Schedule End Date (Sub Assembly Items)")),
                "type_of_manufacturing":    _str(_get(row, "Manufacturing Type (Sub Assembly Items)")),
                "supplier":                 _str(_get(row, "Supplier (Sub Assembly Items)")),
            })

        # ── MR row (Raw Materials) ─────────────────────────────────────────
        mr_id = _get(row, "ID (Raw Materials)")
        if mr_id and mr_id not in bucket["_mr_seen"]:
            bucket["_mr_seen"].add(mr_id)
            bucket["mr_items"].append({
                "name":              str(mr_id),
                "item_code":         _str(_get(row, "Item Code (Raw Materials)")),
                "item_name":         _str(_get(row, "Item Name (Raw Materials)")),
                "quantity":          _get(row, "Plan to Request Qty (Raw Materials)") or _get(row, "Qty As Per BOM (Raw Materials)") or _get(row, "Quantity (Raw Materials)") or 0,
                "schedule_date":     _str(_get(row, "Required By (Raw Materials)")),
                "custom_start_date": _str(_get(row, "Start Date (Raw Materials)")),
                "custom_supplier":   _str(_get(row, "Supplier (Raw Materials)")),
            })

    # Remove internal dedup sets before returning
    for pp_name in pp_data:
        for k in ("_fg_seen", "_sfg_seen", "_mr_seen"):
            pp_data[pp_name].pop(k, None)

    return pp_data


# ─── PP Importer Log APIs ─────────────────────────────────────────────────────
# Persists HOT edits server-side so they survive browser-data clearing / page
# navigations. One log entry per field change; latest entry per
# (pp_name, table_name, row_name, field_name) wins on replay.

import json as _json_mod  # noqa: E402  (already imported via frappe but needs alias)


@frappe.whitelist()
def batch_log_hot_changes(importer_doc: str, changes: list | str) -> dict:
    """
    Insert multiple PP Importer Log entries in a single call.

    Args:
        importer_doc: Name of the Production Plan Importer document.
        changes: JSON array of {pp_name, table_name, row_name, field_name,
                                old_value, new_value} objects.
    """
    if isinstance(changes, str):
        changes = _json_mod.loads(changes)

    for c in changes:
        frappe.get_doc({
            "doctype":      "PP Importer Log",
            "importer_doc": importer_doc,
            "pp_name":      c.get("pp_name",    ""),
            "table_name":   c.get("table_name", ""),
            "row_name":     c.get("row_name",   ""),
            "field_name":   c.get("field_name", ""),
            "old_value":    str(c.get("old_value", "") or ""),
            "new_value":    str(c.get("new_value", "") or ""),
        }).insert(ignore_permissions=True)

    frappe.db.commit()
    return {"status": "ok", "count": len(changes)}


@frappe.whitelist()
def get_hot_log(pp_names: list | str) -> list[dict]:
    """
    Return all PP Importer Log entries for the given pp_names list, ordered by
    name ASC (sequential autoname → chronological order).
    pp_names includes actual Production Plan names AND the importer doc name
    (used as scope key for global settings entries).
    The caller replays them in order; latest write per field wins.
    """
    if isinstance(pp_names, str):
        pp_names = _json_mod.loads(pp_names)
    if not pp_names:
        return []
    return frappe.db.get_all(
        "PP Importer Log",
        filters=[["pp_name", "in", pp_names]],
        fields=["pp_name", "table_name", "row_name", "field_name", "new_value"],
        order_by="name asc",
        limit=0,
    )


@frappe.whitelist()
def clear_hot_log(pp_names: list | str) -> dict:
    """
    Delete all PP Importer Log entries for the given pp_names list.
    Called after a successful Apply so the log doesn't accumulate stale data.
    pp_names includes actual Production Plan names AND the importer doc name
    (for global settings entries).
    """
    if isinstance(pp_names, str):
        pp_names = _json_mod.loads(pp_names)
    if pp_names:
        frappe.db.delete("PP Importer Log", [["pp_name", "in", pp_names]])
        frappe.db.commit()
    return {"status": "ok"}


@frappe.whitelist()
def apply_pp_import(
    importer_doc: str,
    production_plan_name: str,
    po_items_data: list | str,
    sfg_data: list | str,
    mr_data: list | str,
) -> dict:
    """
    Wrapper around save_managed_dates that writes a PP Import Log entry.

    Direct frappe.db.set_value calls bypass validate / before_save hooks.
    Returns {"status": "ok"} on success or {"status": "error", "message": str} on failure.
    """
    import json as _json
    import traceback as _tb

    if isinstance(po_items_data, str):
        po_items_data = _json.loads(po_items_data)
    if isinstance(sfg_data, str):
        sfg_data = _json.loads(sfg_data)
    if isinstance(mr_data, str):
        mr_data = _json.loads(mr_data)

    fg_count  = len(po_items_data or [])
    sfg_count = len(sfg_data or [])
    mr_count  = len(mr_data or [])

    try:
        save_managed_dates(production_plan_name, po_items_data, sfg_data, mr_data)
        frappe.get_doc({
            "doctype":      "PP Import Log",
            "importer_doc": importer_doc,
            "pp_name":      production_plan_name,
            "imported_at":  now_datetime(),
            "status":       "Success",
            "fg_count":     fg_count,
            "sfg_count":    sfg_count,
            "mr_count":     mr_count,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        return {"status": "ok"}

    except Exception:
        err = _tb.format_exc()
        frappe.log_error(err, f"PP Import Error — {production_plan_name}")
        frappe.get_doc({
            "doctype":       "PP Import Log",
            "importer_doc":  importer_doc,
            "pp_name":       production_plan_name,
            "imported_at":   now_datetime(),
            "status":        "Error",
            "fg_count":      fg_count,
            "sfg_count":     sfg_count,
            "mr_count":      mr_count,
            "error_message": err,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        # Return the last non-empty line as the short message
        short = next((l.strip() for l in reversed(err.splitlines()) if l.strip()), "Unknown error")
        return {"status": "error", "message": short}


@frappe.whitelist()
def get_import_log_status(importer_doc: str, pp_names: list | str) -> dict:
    """
    Returns the latest PP Import Log result per pp_name for this importer_doc.
    Used on page load to restore the Imported overlay after a browser refresh.

    Returns:
        { pp_name: { "status": "Success"/"Error", "error_message": str } }
        Only the most-recent entry per pp_name is returned.
    """
    if isinstance(pp_names, str):
        pp_names = _json_mod.loads(pp_names)
    if not pp_names:
        return {}

    rows = frappe.db.get_all(
        "PP Import Log",
        filters={"importer_doc": importer_doc, "pp_name": ["in", pp_names]},
        fields=["pp_name", "status", "error_message", "imported_at"],
        order_by="imported_at asc",   # asc so latest entry overwrites earlier ones
        limit=0,
    )

    result = {}
    for row in rows:
        result[row["pp_name"]] = {
            "status":        row["status"],
            "error_message": row.get("error_message") or "",
        }
    return result


@frappe.whitelist()
def update_importer_status(importer_doc: str, all_pp_names: list | str) -> dict:
    """
    Compute and persist the overall status on the Production Plan Importer doc.

    Rules (based on latest PP Import Log entry per pp_name):
        Fully Imported    → every pp_name has a latest "Success" entry
        Partially Imported → at least one "Success", at least one not
        Pending Import    → none have a "Success" entry (default / all failed)
    """
    if isinstance(all_pp_names, str):
        all_pp_names = _json_mod.loads(all_pp_names)
    if not all_pp_names:
        return {"status": "ok"}

    rows = frappe.db.get_all(
        "PP Import Log",
        filters={"importer_doc": importer_doc, "pp_name": ["in", all_pp_names]},
        fields=["pp_name", "status", "imported_at"],
        order_by="imported_at asc",   # asc → last write per pp_name wins
        limit=0,
    )

    latest: dict[str, str] = {}
    for row in rows:
        latest[row["pp_name"]] = row["status"]   # overwrites with newer entry

    success_count = sum(1 for pp in all_pp_names if latest.get(pp) == "Success")
    total         = len(all_pp_names)

    if success_count == 0:
        new_status = "Pending Import"
    elif success_count == total:
        new_status = "Fully Imported"
    else:
        new_status = "Partially Imported"

    frappe.db.set_value(
        "Production Plan Importer", importer_doc,
        "status", new_status,
        update_modified=False,
    )
    frappe.db.commit()
    return {"status": "ok", "importer_status": new_status}
