import frappe


def create_fields():
    fields_to_create = [
        {
            "fieldname": "source_document_section",
            "fieldtype": "Section Break",
            "label": "Source Document",
            "collapsible": 1,
            "insert_after": "more_info",
        },
        {
            "fieldname": "reference_doctype",
            "fieldtype": "Link",
            "label": "Source Document Type",
            "options": "DocType",
            "read_only": 1,
            "ignore_user_permissions": 1,
            "no_copy": 1,
            "insert_after": "source_document_section",
        },
        {
            "fieldname": "column_break_source_doc",
            "fieldtype": "Column Break",
            "insert_after": "reference_doctype",
        },
        {
            "fieldname": "reference_name",
            "fieldtype": "Dynamic Link",
            "label": "Source Document Name",
            "options": "reference_doctype",
            "read_only": 1,
            "no_copy": 1,
            "insert_after": "column_break_source_doc",
        },
        {
            "fieldname": "posting_date",
            "fieldtype": "Date",
            "label": "Posting Date",
            "read_only": 1,
            "no_copy": 1,
            "insert_after": "reference_name",
        },
    ]

    # Loop to create fields if they don't exist.
    for df in fields_to_create:
        if not frappe.db.exists(
            "Custom Field", {"dt": "Serial No", "fieldname": df["fieldname"]}
        ):
            df["dt"] = "Serial No"
            frappe.get_doc({"doctype": "Custom Field", **df}).insert()
