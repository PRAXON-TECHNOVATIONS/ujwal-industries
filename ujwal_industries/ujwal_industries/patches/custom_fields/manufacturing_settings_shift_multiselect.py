import frappe


def execute():
    """
    Migrate default_shift_type custom field on Manufacturing Settings
    from Link → Table MultiSelect (Bulk PP Planning Shift).

    Run as a fresh patch because the original manufacturing_seting patch
    already ran (with the old Link fieldtype) and won't be re-executed.
    """
    dt = "Manufacturing Settings"
    fieldname = "default_shift_type"

    existing = frappe.db.get_value(
        "Custom Field",
        {"dt": dt, "fieldname": fieldname},
        ["name", "fieldtype"],
        as_dict=True,
    )

    if existing:
        if existing.fieldtype == "Table MultiSelect":
            # Already correct — nothing to do
            return
        # Delete old field (Link) so we can recreate as Table MultiSelect
        frappe.delete_doc("Custom Field", existing.name, ignore_permissions=True)
        frappe.db.commit()

    # Create the correct Table MultiSelect field
    frappe.get_doc(
        {
            "doctype": "Custom Field",
            "dt": dt,
            "fieldname": fieldname,
            "fieldtype": "Table MultiSelect",
            "label": "Shift Types for Planning",
            "options": "Bulk PP Planning Shift",
            "description": (
                "Select one or more shift types for production scheduling. "
                "Multiple shifts combine their working minutes."
            ),
            "insert_after": "enable_shift_wise_scheduling",
        }
    ).insert()
    frappe.db.commit()
