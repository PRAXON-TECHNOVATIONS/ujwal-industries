import frappe
import erpnext.stock.reorder_item

# 1. Store Original Function
original_create_material_request = erpnext.stock.reorder_item.create_material_request

# 2. Wrapper Function
def create_material_request_wrapper(material_requests):
    try:
        frappe.flags.in_auto_reorder_process = True
        return original_create_material_request(material_requests)
    finally:
        frappe.flags.in_auto_reorder_process = False

# 3. Hook Handler
def set_reorder_field(doc, method):
    if frappe.flags.in_auto_reorder_process:
        doc.custom_custom_material_request_type = "Reorder"

erpnext.stock.reorder_item.create_material_request = create_material_request_wrapper