import frappe


def execute():
    """Patch entry point - creates custom fields for Manufacturing Settings"""
    print("it tan")
    create_fields()


def create_fields():
    """Create custom fields for Manufacturing Settings to control backdated planned_start_date"""

    fields_to_create = [
        {
            "fieldname": "production_plan_section",
            "fieldtype": "Section Break",
            "label": "Production Plan Settings",
            "insert_after": "disable_capacity_planning",
        },
        {
            "fieldname": "allow_backdated_planned_start_date",
            "fieldtype": "Check",
            "label": "Allow Backdated Planned Start Date",
            "description": "If unchecked, users cannot set Planned Start Date in Production Plan to a past date",
            "default": "1",
            "insert_after": "production_plan_section",
        },
        {
            "fieldname": "enable_shift_wise_scheduling",
            "fieldtype": "Check",
            "label": "Enable Shift-wise Scheduling",
            "description": "If checked, production dates will be calculated shiftwise based on settings.",
            "default": "1",
            "insert_after": "allow_backdated_planned_start_date",
        },
        {
            "fieldname": "default_shift_type",
            "fieldtype": "Table MultiSelect",
            "label": "Shift Types for Planning",
            "options": "Bulk PP Planning Shift",
            "description": "Select one or more shift types for production scheduling. Multiple shifts combine their working minutes.",
            "insert_after": "enable_shift_wise_scheduling",
        },
    ]

    for df in fields_to_create:
        if not frappe.db.exists(
            "Custom Field", {"dt": "Manufacturing Settings", "fieldname": df["fieldname"]}
        ):
            df["dt"] = "Manufacturing Settings"
            frappe.get_doc({"doctype": "Custom Field", **df}).insert()
            frappe.db.commit()
