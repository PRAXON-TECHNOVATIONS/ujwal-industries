import frappe
from ujwal_industries.ujwal_industries.doctype.document_series_settings.document_series_settings import get_next_number


def numeric_series(doc, method=None):
    if frappe.flags.in_install or frappe.flags.in_migrate:
        return

    if doc.doctype == "Asset":
        return

    if doc.doctype in ["Document Series Settings", "Document Series Table", "Purchase Order"]:
        return

    next_number = get_next_number(doc.doctype)

    if next_number:
        doc.name = next_number
