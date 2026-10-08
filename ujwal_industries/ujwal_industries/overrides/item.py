# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def sync_subcontract_cost_to_boms(doc: Document, method: str | None = None) -> None:
    """Whenever an Item's subcontract data is saved, refresh
    custom_subcontract_operation_cost (and cascade to parent BOMs) on every
    active, submitted BOM for this item — so BOM's Total Cost reflects the
    item's current default Subcontract rate without anyone needing to
    manually revisit each BOM. Cheap and idempotent, so this just always
    re-syncs rather than trying to detect exactly what changed."""
    if not doc.get("custom_subcontracting_suppliers"):
        return

    from ujwal_industries.ujwal_industries.overrides.bom_subcontract_cost import (
        refresh_subcontract_operation_cost,
    )

    bom_names = frappe.get_all(
        "BOM", filters={"item": doc.name, "docstatus": 1, "is_active": 1}, pluck="name"
    )
    for bom_name in bom_names:
        refresh_subcontract_operation_cost(bom_name)

def validate_subcontracting_suppliers(doc: Document, method: str | None = None) -> None:
    """
    Validate Item Subcontracting Supplier table.

    Rules:
    1. Exactly one default row per custom_type (In House / Subcontract /
       In House - Vendor), across the whole item regardless of Company.
       This is a safety net for the same rule the Item form's client-side JS
       enforces interactively -- it self-corrects here (rather than blocking
       the save) so rows created outside the form (Data Import, API, bulk
       edit) can't leave a type with zero or multiple defaults.
    2. No duplicate (company, supplier) combinations.

    Args:
        doc: Item document
        method: Hook method name (not used)
    """
    if not doc.get("custom_subcontracting_suppliers"):
        return

    # Track unique (company, supplier) combinations
    seen_combinations: set[tuple[str, str]] = set()

    rows_by_type: dict[str, list] = {}

    for idx, row in enumerate(doc.custom_subcontracting_suppliers, start=1):
        # Check for duplicate (company, supplier)
        key = (row.company, row.supplier)
        if key in seen_combinations:
            frappe.throw(
                _("Row #{0}: Duplicate supplier '{1}' for company '{2}' in Subcontracting Suppliers table").format(
                    idx, frappe.bold(row.supplier), frappe.bold(row.company)
                )
            )
        seen_combinations.add(key)

        # Validate lead_time_days is non-negative
        if row.lead_time_days and row.lead_time_days < 0:
            frappe.throw(
                _("Row #{0}: Lead Time Days cannot be negative").format(idx)
            )

        if row.custom_type:
            rows_by_type.setdefault(row.custom_type, []).append(row)

    for type_rows in rows_by_type.values():
        defaults = [row for row in type_rows if row.is_default]

        if len(defaults) == 0:
            # No default for this type -- pick the first row as default,
            # same as the "auto-default the first row" behaviour on the form.
            type_rows[0].is_default = 1
        elif len(defaults) > 1:
            # Multiple defaults for this type -- keep only the last one
            # (matches the form's "ticking a new default clears the old one").
            for row in defaults[:-1]:
                row.is_default = 0




def autoname(self, method):
    if not self.custom_material_type:
        return
    
    stock_setting = frappe.get_single("Stock Settings")
    if stock_setting.applicable_naming_series == 1:
        matched_row = None
        if stock_setting.item_naming_series:
            for row in stock_setting.item_naming_series:
                if row.item_group == self.custom_material_type:
                    matched_row = row
                    break
        
        if not matched_row:
            frappe.throw(f"No Naming Series Defined for Material Type in Stock Settings<br> <b>{self.custom_material_type}</b>")
        
        
        from_start = int(matched_row.from_start)
        to_end = int(matched_row.to_end) 
        
        frappe.db.sql(
                """
                SELECT current_no
                FROM `tabItem Naming Series`
                WHERE name = %s
                FOR UPDATE
                """,matched_row.name)

        current_no = frappe.db.get_value("Item Naming Series", matched_row.name, "current_no")

        if current_no:
            try:
                current_no_int = int(''.join(filter(str.isdigit, current_no)))
            except:
                current_no_int = 0
        else:
            current_no_int = from_start

        next_no = current_no_int + 1

        if next_no > to_end:
            frappe.throw(
                f"Naming series out of range for Material Type {self.custom_material_type}. "
                f"Allowed Range: {from_start} to {to_end}"
            )

        self.name = str(next_no)

        frappe.db.set_value("Item Naming Series", matched_row.name,"current_no",next_no)
    
    else:
        frappe.msgprint("Dynamic Item Naming Series is Currently Disabled in Stock Settings. Please Enable it to Apply Automatic Numbering.")