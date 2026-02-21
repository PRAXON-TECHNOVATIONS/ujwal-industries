import frappe


def execute():
    """Patch entry point — adds Planned End Date field to Production Plan Item."""
    create_fields()


def create_fields():
    """Add custom_planned_end_date (Datetime) to Production Plan Item child table."""
    field_def = {
        "dt": "Production Plan Item",
        "fieldname": "custom_planned_end_date",
        "label": "Planned End Date",
        "fieldtype": "Datetime",
        "insert_after": "planned_start_date",
        "read_only": 1,
        "in_list_view": 1,
        "description": "Auto-calculated: when production will finish if started at Planned Start Date (shift + holiday aware).",
    }

    if not frappe.db.exists(
        "Custom Field",
        {"dt": "Production Plan Item", "fieldname": "custom_planned_end_date"},
    ):
        frappe.get_doc({"doctype": "Custom Field", **field_def}).insert()
        frappe.db.commit()
