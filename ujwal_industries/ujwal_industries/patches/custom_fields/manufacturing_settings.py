import frappe


def execute():
    """Patch entry point - creates custom fields for Manufacturing Settings"""
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
    ]

    for df in fields_to_create:
        if not frappe.db.exists(
            "Custom Field", {"dt": "Manufacturing Settings", "fieldname": df["fieldname"]}
        ):
            df["dt"] = "Manufacturing Settings"
            frappe.get_doc({"doctype": "Custom Field", **df}).insert()
            frappe.db.commit()
