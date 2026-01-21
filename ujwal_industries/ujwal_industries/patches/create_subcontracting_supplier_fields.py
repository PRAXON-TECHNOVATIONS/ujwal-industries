# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    """Create custom fields for Item Subcontracting Supplier table"""

    custom_fields = {
        "Item": [
            {
                "fieldname": "custom_subcontracting_suppliers_section",
                "fieldtype": "Section Break",
                "label": "Subcontracting Suppliers",
                "insert_after": "supplier_items",
                "description": "Define multiple subcontracting suppliers with their lead times for this item"
            },
            {
                "fieldname": "custom_subcontracting_suppliers",
                "fieldtype": "Table",
                "label": "Subcontracting Suppliers",
                "options": "Item Subcontracting Supplier",
                "insert_after": "custom_subcontracting_suppliers_section"
            }
        ]
    }

    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()

    print("✓ Custom fields for Item Subcontracting Supplier created successfully")
