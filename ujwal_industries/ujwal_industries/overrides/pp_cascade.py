# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""
Cascade / propagation functions for Production Plan.
Handles client-triggered cascades: SFG date changes flowing to parent SFGs and MR items,
and MR item date changes flowing to SFGs and FG items.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe
from frappe.model.document import Document  # type: ignore[import-untyped]
from frappe.utils import add_days, add_to_date, getdate, get_datetime

from .pp_utils import (
    _to_datetime,
    get_supplier_lead_time,
    get_subcontract_lead_time,
    calculate_production_time_from_bom,
)
from .pp_sfg_dates import calculate_fg_dates_from_subassembly


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
    affected_sfgs: dict[str, Any] = {}  # production_item -> new_end_date (datetime)

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
