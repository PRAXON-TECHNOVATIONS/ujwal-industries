
import frappe

def validate(doc, method):
    if doc.item_naming_series:
        for i in doc.item_naming_series:
            if i.current_no:
                i.db_set('current_no','')
                frappe.db.commit()       

    
    seen = set()
    for row in doc.item_naming_series:
        if row.item_group in seen:
            frappe.throw(f"Item Group <b>{row.item_group}</b> already added in Item Naming Series")
        seen.add(row.item_group)                