import frappe
from ujwal_industries.ujwal_industries.doctype.document_series_settings.document_series_settings import get_next_number


def numeric_series(doc, method=None):

    if doc.doctype in ["Document Series Settings", "Document Series Table"]:
        return

    next_number = get_next_number(doc.doctype)

    if next_number:
        doc.name = next_number