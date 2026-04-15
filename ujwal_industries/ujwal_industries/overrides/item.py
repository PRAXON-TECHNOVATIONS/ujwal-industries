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


