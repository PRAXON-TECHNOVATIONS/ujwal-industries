import frappe
from frappe import _


def before_insert(doc, method):
    if doc.amended_from:
        if frappe.db.exists("Sales Invoice", doc.amended_from):
            frappe.delete_doc("Sales Invoice", doc.amended_from, force=1)
        
        doc.name = doc.amended_from
        doc.amended_from = None

# def validate_sales_invoice_sequence(doc, method):
#     for item in doc.items:
#         if not item.sales_order:
#             continue

#         so_items = frappe.get_all("Sales Order Item", filters={"parent": item.sales_order},fields=["name", "item_code", "idx"])
#         so_items = sorted(so_items, key=lambda x: x.idx)

#         try:
#             so_item = so_items[item.idx - 1]  
#         except IndexError:
#             frappe.throw(
#                 _("Row {0}: Item sequence exceeds Sales Order length").format(item.idx)
#             )
            
#         so_link = f"<a href='/app/sales-order/{item.sales_order}' target='_blank'>{item.sales_order}</a>"

#         if item.item_code != so_item.item_code:
#             frappe.throw(
#                 _("Row {0}: Item sequence mismatch with Sales Order {1}. Expected Item: {2}, Found: {3}")
#                 .format(item.idx, so_link, so_item.item_code, item.item_code)
#             )


def autoname(doc, method):

    invoice_type = None

    if doc.get("custom_is_labour"):
        invoice_type = "Labour Invoice"

    elif doc.get("custom_service_sale_invoice"):
        invoice_type = "Service sale invoice"
        
    elif doc.get("custom_sub_invoice"):
        invoice_type = "Sub invoice"     
        
    elif doc.get("custom_invoice_type") == "Export":
        invoice_type = "Export Invoice"
        
    elif doc.get("custom_invoice_type") == "Local":
        invoice_type = ""     

    if invoice_type is None:
        return

    settings = frappe.get_doc("Document Series Settings")
    for row in settings.document_series:

        if (
            row.document_type == "Sales Invoice"
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