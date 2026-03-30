
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


@frappe.whitelist()
def after_install():
    stock_custom_filed()
    byuing_custom_filed()
    
   

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
            "label": _("Applicable Naming Series"),
            "fieldname": "applicable_naming_series",
            "fieldtype": "Check",
            "insert_after": "ins_section",   
        },
    )
    create_custom_field(
        "Stock Settings",
        {
            "label": _("Item Naming Series"),
            "fieldname": "item_naming_series",
            "fieldtype": "Table",
            "options": "Item Naming Series",
            "insert_after": "applicable_naming_series",
        },
    )
        

    
def byuing_custom_filed():
    create_custom_field(
        "Buying Settings",
        {
            "label": _("Naming Series"),
            "fieldname": "ins_tab",
            "fieldtype": "Tab Break",
            "insert_after": "fixed_email",   
        },
    )
    
    create_custom_field(
        "Buying Settings",
        {
            "label": _(""),
            "fieldname": "ins_section",
            "fieldtype": "Section Break",
            "insert_after": "ins_tab",
        },
    )
    create_custom_field(
        "Buying Settings",
        {
            "label": _("Applicable Customer Naming Series"),
            "fieldname": "applicable_customer_naming_series",
            "fieldtype": "Check",
            "insert_after": "ins_section",   
        },
    )
    create_custom_field(
        "Buying Settings",
        {
            "label": _("Customer Naming Series"),
            "fieldname": "customer_naming_series",
            "fieldtype": "Table",
            "options": "Customer Naming Series",
            "insert_after": "applicable_customer_naming_series",
            "depends_on": "eval: doc.applicable_customer_naming_series == 1",   
        },
    )
    
    create_custom_field(
        "Buying Settings",
        {
            "label": _("Applicable Supplier Naming Series"),
            "fieldname": "applicable_supplier_naming_series",
            "fieldtype": "Check",
            "insert_after": "applicable_customer_naming_series",   
        },
    )
    create_custom_field(
        "Buying Settings",
        {
            "label": _("Supplier Naming Series"),
            "fieldname": "supplier_naming_series",
            "fieldtype": "Table",
            "options": "Supplier Naming Series",
            "insert_after": "applicable_supplier_naming_series",
            "depends_on": "eval: doc.applicable_supplier_naming_series == 1",   
        },
    )
    
    