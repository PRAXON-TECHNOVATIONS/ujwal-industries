import frappe


def create_fields():
    field_definition = {
        "fieldname": "tool_type",
        "fieldtype": "Select",
        "label": "Tool Type",
        "options": "\nNew\nOld",
        "insert_after": "asset_category",
        "reqd": 0,
    }

    custom_field_name = frappe.db.get_value(
        "Custom Field", {"dt": "Asset", "fieldname": field_definition["fieldname"]}, "name"
    )
    if not custom_field_name:
        field_definition["dt"] = "Asset"
        frappe.get_doc({"doctype": "Custom Field", **field_definition}).insert()
        return

    frappe.db.set_value("Custom Field", custom_field_name, "reqd", 0, update_modified=False)
