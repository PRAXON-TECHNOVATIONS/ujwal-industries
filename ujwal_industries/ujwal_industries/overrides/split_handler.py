# Copyright (c) 2026, Ujwal Industries
# License: MIT
"""
Split row handler for Production Plan items.
Manages INSERT/UPDATE/DELETE operations for split rows from the Production Plan Importer.

For parallel planning:
- Original row ID is preserved and updated with qty1 and calculated dates
- New rows are created with new IDs, qty2, and different dates
- Split rows have names like "new_<timestamp>_<randomid>" (created by frontend)
"""

from __future__ import annotations

from typing import Any
import frappe
from frappe.utils import now_datetime


# NOTE: currently unused in active apply flow (kept for potential re-enable).
def handle_split_rows(
    production_plan_name: str,
    po_items_data: list[dict[str, Any]],
    sfg_data: list[dict[str, Any]],
    mr_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Process split rows for parallel planning:
    - Rows with name="new_*" are NEW rows (insert them with real IDs)
    - Rows with old IDs are UPDATED rows (update their qty and dates)
    - Rows removed are DELETED
    
    Returns: {
        "inserted": { "fg": N, "sfg": N, "mr": N },
        "updated": { "fg": N, "sfg": N, "mr": N },
        "deleted": { "fg": N, "sfg": N, "mr": N },
    }
    """
    doc = frappe.get_doc("Production Plan", production_plan_name)
    
    # Fetch original DB state
    original_fg = {row.name: row.as_dict() for row in (doc.po_items or [])}
    original_sfg = {row.name: row.as_dict() for row in (doc.sub_assembly_items or [])}
    original_mr = {row.name: row.as_dict() for row in (doc.mr_items or [])}
    
    result = {
        "inserted": {"fg": 0, "sfg": 0, "mr": 0},
        "updated": {"fg": 0, "sfg": 0, "mr": 0},
        "deleted": {"fg": 0, "sfg": 0, "mr": 0},
    }
    
    # Process FG items
    _result_fg = _process_split_table(
        "Production Plan Item",
        original_fg,
        po_items_data or [],
        production_plan_name,
    )
    result["inserted"]["fg"] = _result_fg[0]
    result["updated"]["fg"] = _result_fg[1]
    result["deleted"]["fg"] = _result_fg[2]
    
    # Process SFG items
    _result_sfg = _process_split_table(
        "Production Plan Sub Assembly Item",
        original_sfg,
        sfg_data or [],
        production_plan_name,
    )
    result["inserted"]["sfg"] = _result_sfg[0]
    result["updated"]["sfg"] = _result_sfg[1]
    result["deleted"]["sfg"] = _result_sfg[2]
    
    # Process MR items
    _result_mr = _process_split_table(
        "Material Request Plan Item",
        original_mr,
        mr_data or [],
        production_plan_name,
    )
    result["inserted"]["mr"] = _result_mr[0]
    result["updated"]["mr"] = _result_mr[1]
    result["deleted"]["mr"] = _result_mr[2]
    
    return result


def _process_split_table(
    doctype: str,
    original_db: dict[str, Any],
    incoming_data: list[dict[str, Any]],
    production_plan_name: str,
) -> tuple[int, int, int]:
    """
    Process one table for splits.
    
    For NEW rows (name="new_*"):
    - Match to original DB row by item code + finding corresponding updated row
    - Copy ALL fields from source DB row (fixes NULL fields from frontend)
    - Override only qty and date fields with split values
    
    Returns: (inserted_count, updated_count, deleted_count)
    """
    inserted = 0
    updated = 0
    deleted = 0
    
    incoming_names = set()
    
    # Build lookup map of existing non-"new_*" rows (to find their sources)
    existing_incoming = {r.get("name"): r for r in incoming_data if r.get("name") and not str(r.get("name")).startswith("new_")}
    
    def find_source_row_for_new(new_row_data: dict[str, Any]) -> dict[str, Any] | None:
        """
        Match a new_* row to its source/parent DB row.
        
        The original row being split will:
        1. Have matching production_item/item_code
        2. Be in existing_incoming (has updated qty/dates)
        3. Be the one that had split() applied to it
        
        We match by:
        - Item field (production_item or item_code depending on doctype)
        - Parent row MUST exist in existing_incoming (being updated with new qty)
        """
        item_field = {
            "Production Plan Item": "item_code",
            "Production Plan Sub Assembly Item": "production_item",
            "Material Request Plan Item": "item_code",
        }.get(doctype, "item_code")
        
        new_item = new_row_data.get(item_field)
        if not new_item:
            return None
        
        # Find DB row that matches item AND is being updated (in existing_incoming)
        # This ensures we get the parent row that was split
        for db_name, db_row in original_db.items():
            if (db_row.get(item_field) == new_item and 
                db_name in existing_incoming):
                # This is the parent row! Copy ALL its fields (bom_no, production_item, item_name, warehouse, etc)
                return db_row

        return None
    
    # Process each incoming row
    for row_data in incoming_data:
        name = row_data.get("name")
        if not name:
            continue
        
        is_new_row = str(name).startswith("new_")
        
        if is_new_row:
            # This is a split row - INSERT with real ID
            # Find its source DB row to get ALL fields
            source_row = find_source_row_for_new(row_data)
            incoming_names.add(name)
            if _insert_new_split_row(doctype, row_data, production_plan_name, source_row):
                inserted += 1
        else:
            # Existing row - UPDATE qty/date fields only
            incoming_names.add(name)
            if name in original_db:
                if _update_existing_row(doctype, name, row_data):
                    updated += 1
    
    # Delete rows not in incoming
    for original_name in original_db.keys():
        if original_name not in incoming_names:
            if _delete_row(doctype, original_name):
                deleted += 1
    
    return inserted, updated, deleted


def _insert_new_split_row(
    doctype: str,
    row_data: dict[str, Any],
    production_plan_name: str,
    source_row: dict[str, Any] | None = None,
) -> bool:
    """
    Insert new split row with real ID.
    
    Process:
    1. Copy ALL fields from source_row (handles NULL values from frontend)
    2. Override qty and date fields with split values from row_data
    3. Replace temp "new_*" ID with real UUID
    
    Returns: True if inserted, False if failed.
    """
    try:
        # Generate Frappe-style short ID (like 9vs7qd4ii6 instead of long UUID)
        real_name = frappe.generate_hash(length=10)
        
        # If we have a source row, start with ALL its fields (excludes system fields)
        # This preserves: bom_no, production_item, item_name, fg_warehouse, parent_item_code, etc.
        if source_row:
            fields = {k: v for k, v in source_row.items() 
                     if k not in ["name", "creation", "modified", "modified_by", "owner", 
                                 "idx", "parent", "parenttype", "docstatus"]}
        else:
            # Fallback: use whatever the frontend sent (may have NULLs)
            # This is not ideal but ensures we insert something
            fields = {k: v for k, v in row_data.items() 
                     if k not in ["name", "creation", "modified", "modified_by", "owner", "docstatus"]}
        
        # Override ONLY qty and date fields with split values from row_data
        # These are the ONLY fields that differ between source and split
        # DO NOT override item, supplier, bom, warehouse, etc from row_data (they may be NULL)
        qty_date_fields = {
            "Production Plan Item": ["planned_qty", "planned_start_date", "custom_planned_end_date"],
            "Production Plan Sub Assembly Item": ["qty", "schedule_date", "custom_schedule_end_date"],
            "Material Request Plan Item": ["quantity", "custom_start_date", "schedule_date"],
        }.get(doctype, [])
        
        for field_key in qty_date_fields:
            if field_key in row_data and row_data[field_key] is not None:
                fields[field_key] = row_data[field_key]
        
        # Get next idx
        next_idx = frappe.db.sql(
            f"SELECT COALESCE(MAX(idx), 0) + 1 FROM `tab{doctype}` WHERE `parent` = %s",
            [production_plan_name]
        )[0][0]
        
        # Set system fields
        fields.update({
            "name": real_name,
            "parent": production_plan_name,
            "idx": next_idx,
            "creation": now_datetime(),
            "modified": now_datetime(),
            "modified_by": frappe.session.user,
            "owner": frappe.session.user,
            "parenttype": doctype,
            "docstatus": 0,
        })
        
        # Insert with parameterized query
        field_names = list(fields.keys())
        placeholders = ["%s"] * len(field_names)
        values = list(fields.values())
        
        insert_sql = f"INSERT INTO `tab{doctype}` ({', '.join(f'`{f}`' for f in field_names)}) VALUES ({', '.join(placeholders)})"
        
        frappe.db.sql(insert_sql, values)
        frappe.db.commit()
        
        return True
        
    except Exception:
        return False


def _update_existing_row(doctype: str, row_name: str, row_data: dict[str, Any]) -> bool:
    """
    Update an existing row with new qty and date values from the split.
    Uses parameterized SQL.
    
    Returns: True if updated, False otherwise.
    """
    try:
        # Get field mapping
        field_mapping = _get_field_mapping(doctype)
        
        # Build updates dict
        updates = {}
        for db_field, data_key in field_mapping.items():
            if data_key in row_data and row_data[data_key] is not None:
                updates[db_field] = row_data[data_key]
        
        if not updates:
            return False  # No changes
        
        # Always update metadata
        updates["modified"] = now_datetime()
        updates["modified_by"] = frappe.session.user
        
        # Build parameterized UPDATE
        set_clauses = [f"`{field}` = %s" for field in updates.keys()]
        values = list(updates.values())
        values.append(row_name)  # For WHERE clause
        
        update_sql = f"UPDATE `tab{doctype}` SET {', '.join(set_clauses)} WHERE `name` = %s"
        
        frappe.db.sql(update_sql, values)
        frappe.db.commit()
        
        return True
        
    except Exception:
        return False


def _delete_row(doctype: str, row_name: str) -> bool:
    """
    Delete a row that was removed in the split.
    
    Returns: True if deleted, False if not found.
    """
    try:
        delete_sql = f"DELETE FROM `tab{doctype}` WHERE `name` = %s"
        frappe.db.sql(delete_sql, [row_name])
        frappe.db.commit()
        
        return True
        
    except Exception:
        return False


def _get_field_mapping(doctype: str) -> dict[str, str]:
    """
    Map incoming data keys to database field names.
    Based on the actual field names from the frontend grid.
    """
    if doctype == "Production Plan Item":
        return {
            "item_code": "item_code",
            "planned_qty": "planned_qty",
            "planned_start_date": "planned_start_date",
            "custom_planned_end_date": "custom_planned_end_date",
            "custom_manufacturing_type": "custom_manufacturing_type",
            "custom_supplier": "custom_supplier",
            "sales_order": "sales_order",
            "bom_no": "bom_no",
        }
    elif doctype == "Production Plan Sub Assembly Item":
        return {
            "production_item": "production_item",
            "qty": "qty",
            "schedule_date": "schedule_date",
            "custom_schedule_end_date": "custom_schedule_end_date",
            "type_of_manufacturing": "type_of_manufacturing",
            "supplier": "supplier",
            "bom_no": "bom_no",
            "production_plan_item": "production_plan_item",
            "parent_item_code": "parent_item_code",
            "item_name": "item_name",
        }
    elif doctype == "Material Request Plan Item":
        return {
            "item_code": "item_code",
            "quantity": "quantity",
            "custom_start_date": "custom_start_date",
            "schedule_date": "schedule_date",
            "custom_supplier": "custom_supplier",
            "sales_order": "sales_order",
            "item_name": "item_name",
        }
    return {}

