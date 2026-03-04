# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

def validate_subcontracting_suppliers(doc: Document, method: str | None = None) -> None:
    """
    Validate Item Subcontracting Supplier table.

    Rules:
    1. Only ONE default supplier per (item, company) combination
    2. No duplicate (company, supplier) combinations

    Args:
        doc: Item document
        method: Hook method name (not used)
    """
    if not doc.get("custom_subcontracting_suppliers"):
        return

    # Track defaults per company
    company_defaults: dict[str, str] = {}

    # Track unique (company, supplier) combinations
    seen_combinations: set[tuple[str, str]] = set()

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

        # Check for multiple defaults per company
        if row.is_default:
            if row.company in company_defaults:
                frappe.throw(
                    _("Row #{0}: Only one default subcontracting supplier is allowed per company. "
                      "Company '{1}' already has '{2}' marked as default.").format(
                        idx,
                        frappe.bold(row.company),
                        frappe.bold(company_defaults[row.company])
                    )
                )
            company_defaults[row.company] = row.supplier

        # Validate lead_time_days is non-negative
        if row.lead_time_days and row.lead_time_days < 0:
            frappe.throw(
                _("Row #{0}: Lead Time Days cannot be negative").format(idx)
            )


def autoname(self, method):

    if not self.item_group:
        return
    
    stock_setting = frappe.get_single("Stock Settings")
    
    matched_row = None
    if stock_setting.item_naming_series:
        for row in stock_setting.item_naming_series:
            if row.item_group == self.item_group:
                matched_row = row
                break
    
    if not matched_row:
            frappe.throw(f"No Naming Series defined for Item Group in Stock Settings: {self.item_group}") 
    
    
    from_start = int(matched_row.from_start)
    to_end = int(matched_row.to_end) 
    
    frappe.db.sql(
            """
            SELECT current_no
            FROM `tabItem Naming Series`
            WHERE name = %s
            FOR UPDATE
            """,
            matched_row.name,
        )

    current_no = frappe.db.get_value("Item Naming Series", matched_row.name, "current_no")

    if not current_no:
        next_no = from_start + 1
    else:
        next_no = int(current_no) + 1

    if next_no > to_end:
        frappe.throw(
            f"Naming series out of range for Item Group {self.item_group}. "
            f"Allowed Range: {from_start} to {to_end}"
        )

    self.name = str(next_no)

    frappe.db.set_value("Item Naming Series", matched_row.name,"current_no",next_no)