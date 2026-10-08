import frappe


def create_fields():
    fields = [
        {
            "dt": "Item Subcontracting Supplier",
            "fieldname": "custom_operation",
            "fieldtype": "Link",
            "label": "Operation",
            "options": "Operation",
            "insert_after": "custom_type",
            "depends_on": "eval:doc.custom_type == 'Subcontract'",
            "description": "Used by Cost Estimation's \"Pull from BOM\" to add this item's subcontract step as an Operations row automatically.",
        },
        {
            "dt": "Item Subcontracting Supplier",
            "fieldname": "custom_rate_per_pc",
            "fieldtype": "Float",
            "label": "Rate per Pc",
            "precision": "3",
            "insert_after": "custom_operation",
            "depends_on": "eval:doc.custom_type == 'Subcontract'",
            "description": "Direct subcontract cost per piece — pulled as-is into Cost Estimation's Rate per Pc (no machine/time involved).",
        },
    ]

    for field in fields:
        if frappe.db.exists("Custom Field", {"dt": field["dt"], "fieldname": field["fieldname"]}):
            continue
        frappe.get_doc({"doctype": "Custom Field", **field}).insert()

    frappe.db.commit()


def execute():
    create_fields()
