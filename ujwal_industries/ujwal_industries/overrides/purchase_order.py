
import frappe


def before_insert(doc, method):
    if doc.amended_from:
        if frappe.db.exists("Sales Order", doc.amended_from):
            frappe.delete_doc("Sales Order", doc.amended_from, force=1)
        
        doc.name = doc.amended_from
        doc.amended_from = None
        
        
        

def autoname(doc, method):
    invoice_type = None
    if doc.get("is_subcontracted"):
        invoice_type = "Sub Con PO"

    elif doc.get("custom_service_po"):
        invoice_type = "Service PO"
        
    elif doc.get("custom_purchase_type") == "Import RM":
        invoice_type = "Import RM PO"
        
    elif doc.get("custom_purchase_type") == "Local":
        invoice_type = ""     

    if invoice_type is None:
        return

    settings = frappe.get_doc("Document Series Settings")
    for row in settings.document_series:

        if (
            row.document_type == "Purchase Order"
            and row.type == invoice_type
        ):

            start_number = int(row.start_number)
            end_number = int(row.end_number)

            if not row.current_number:
                new_number = start_number
            else:
                new_number = int(row.current_number) + 1

            if new_number > end_number:
                frappe.throw(f"{invoice_type} series limit exceeded")

            doc.name = str(new_number)
            frappe.db.set_value(row.doctype , row.name, "current_number", new_number)
            break        