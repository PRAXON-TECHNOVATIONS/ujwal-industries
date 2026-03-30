import frappe


def create_fields():
    fields_to_create = [
        {
            "fieldname": "tool_type",
            "fieldtype": "Select",
            "label": "Tool Type",
            "options": "\nNew\nOld",
            "insert_after": "asset_category",
            "reqd": 1,
        }
    ]

    for df in fields_to_create:
        if not frappe.db.exists(
            "Custom Field", {"dt": "Asset", "fieldname": df["fieldname"]}
        ):
            df["dt"] = "Asset"
            frappe.get_doc({"doctype": "Custom Field", **df}).insert()
