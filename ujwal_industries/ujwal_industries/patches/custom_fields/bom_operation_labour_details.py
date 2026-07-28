import frappe


def create_fields():
    field = {
        "dt": "BOM Operation",
        "fieldname": "custom_labour_details",
        "fieldtype": "Table",
        "label": "Labour Details",
        "options": "BOM Operation Labour Detail",
        "description": (
            "Roles working on this operation, their hours and head count, "
            "used for role-wise labour costing in Cost Estimation."
        ),
        "insert_after": "custom_cascade_complete_previous",
        "allow_on_submit": 1,
    }

    if frappe.db.exists("Custom Field", {"dt": "BOM Operation", "fieldname": field["fieldname"]}):
        return

    frappe.get_doc({"doctype": "Custom Field", **field}).insert()
    frappe.db.commit()


def execute():
    create_fields()
