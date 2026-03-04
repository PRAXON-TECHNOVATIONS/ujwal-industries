
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


@frappe.whitelist()
def after_install():
    stock_custom_filed()
    
   

def stock_custom_filed():
    
    create_custom_field(
        "Stock Settings",
        {
            "label": _("Item Naming Series"),
            "fieldname": "ins_tab",
            "fieldtype": "Tab Break",
            "insert_after": "stock_auth_role",   
        },
    )
    
    create_custom_field(
        "Stock Settings",
        {
            "label": _(""),
            "fieldname": "ins_section",
            "fieldtype": "Section Break",
            "insert_after": "ins_tab",
        },
    )
    
    create_custom_field(
        "Stock Settings",
        {
            "label": _("Item Naming Series"),
            "fieldname": "item_naming_series",
            "fieldtype": "Table",
            "options": "Item Naming Series",
            "insert_after": "ins_section",
        },
    )
        

    
    
    