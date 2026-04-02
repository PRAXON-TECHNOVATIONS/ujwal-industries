import frappe
from frappe import _

def validate_sales_invoice_sequence(doc, method):
    for item in doc.items:
        if not item.sales_order:
            continue

        so_items = frappe.get_all("Sales Order Item", filters={"parent": item.sales_order},fields=["name", "item_code", "idx"])
        so_items = sorted(so_items, key=lambda x: x.idx)

        try:
            so_item = so_items[item.idx - 1]  
        except IndexError:
            frappe.throw(
                _("Row {0}: Item sequence exceeds Sales Order length").format(item.idx)
            )
            
        so_link = f"<a href='/app/sales-order/{item.sales_order}' target='_blank'>{item.sales_order}</a>"

        if item.item_code != so_item.item_code:
            frappe.throw(
                _("Row {0}: Item sequence mismatch with Sales Order {1}. Expected Item: {2}, Found: {3}")
                .format(item.idx, so_link, so_item.item_code, item.item_code)
            )