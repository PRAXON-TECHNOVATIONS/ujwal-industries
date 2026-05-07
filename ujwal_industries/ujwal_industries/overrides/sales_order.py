
import frappe


def before_insert(doc, method):
    if doc.amended_from:
        if frappe.db.exists("Sales Order", doc.amended_from):
            frappe.delete_doc("Sales Order", doc.amended_from, force=1)
        
        doc.name = doc.amended_from
        doc.amended_from = None
       
    if doc.customer_name_:
        doc.db_set("customer_name",doc.customer_name_)
        frappe.db.commit()    
           