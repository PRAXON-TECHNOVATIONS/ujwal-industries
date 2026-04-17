import frappe


def create_fields():
    field = {
        "dt": "BOM Operation",
        "fieldname": "custom_cascade_complete_previous",
        "fieldtype": "Check",
        "label": "Cascade Complete Previous",
        "description": (
            "When enabled, all BOM Operations listed above this one "
            "(by Sequence ID) will be automatically marked as complete "
            "when this operation is processed."
        ),
        "insert_after": "fixed_time",
        "in_list_view": 1,
        "default": "0",
    }

    if frappe.db.exists("Custom Field", {"dt": "BOM Operation", "fieldname": field["fieldname"]}):
        return

    frappe.get_doc({"doctype": "Custom Field", **field}).insert()
    frappe.db.commit()


def execute():
    create_fields()
