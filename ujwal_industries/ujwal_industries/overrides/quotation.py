
import frappe


def before_insert(doc, method):
    if doc.amended_from:
        if frappe.db.exists("Quotation", doc.amended_from):
            frappe.delete_doc("Quotation", doc.amended_from, force=1)
        
        doc.name = doc.amended_from
        doc.amended_from = None