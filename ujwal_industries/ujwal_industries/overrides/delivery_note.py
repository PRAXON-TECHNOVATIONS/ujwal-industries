

import frappe


def before_insert(doc, method):
    if doc.customer_name_:
        doc.db_set("customer_name",doc.customer_name_)
        frappe.db.commit()    
           