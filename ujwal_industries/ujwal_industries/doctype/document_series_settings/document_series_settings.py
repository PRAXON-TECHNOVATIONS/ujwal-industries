# Copyright (c) 2026, Ujjwal Aggrawal and contributors
# For license information, please see license.txt

# import frappe
# from frappe.model.document import Document


# # class DocumentSeriesSettings(Document):
# # 	pass

import frappe
from frappe.model.document import Document


class DocumentSeriesSettings(Document):
    
    def validate(self):
        seen = set()

        for row in self.document_series:
            key = (row.document_type, row.type)
            if key in seen:
                frappe.throw(f"Duplicate Document Type not allowed: {row.document_type}")

            seen.add(key)
            if row.start_number:
                if int(row.start_number) >= int(row.end_number):
                    frappe.throw(f"Start Number must be less than End Number for {row.document_type}")
                
                
@frappe.whitelist()
def get_next_number(doctype):

    settings_doc = frappe.get_doc("Document Series Settings")

    for row in settings_doc.document_series:
        if row.type:
            # Rows with a Type are handled by their own doctype autoname
            # logic (e.g. Purchase Order Service/Sub Con PO), skip them here.
            continue

        if row.document_type == doctype:

            start = int(row.start_number)
            end = int(row.end_number)
            current = int(row.current_number or start)

            next_number = current + 1

            if next_number > end:
                frappe.throw(f"Series limit exceeded for {doctype}")

            frappe.db.set_value(
                "Document Series Table",
                row.name,
                "current_number",
                str(next_number)
            )

            return str(next_number)

    return None