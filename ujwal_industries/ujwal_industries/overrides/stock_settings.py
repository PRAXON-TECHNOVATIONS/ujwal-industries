
import frappe

def validate(doc, method):
    if doc.item_naming_series:
        for i in doc.item_naming_series:
            if i.current_no:
                i.db_set('current_no','')
                frappe.db.commit()       