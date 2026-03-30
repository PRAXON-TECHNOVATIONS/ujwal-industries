import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def create_fields():
    fields_to_create = [
        {
            "fieldname": "parent_asset_category",
            "fieldtype": "Link",
            "label": "Parent Asset Category",
            "options": "Asset Category",
            "ignore_user_permissions": 1,
            "insert_after": "asset_category_name",
            "search_index": 1,
        },
        {
            "fieldname": "is_group",
            "fieldtype": "Check",
            "label": "Is Group",
            "default": "0",
            "insert_after": "parent_asset_category",
            "in_list_view": 1,
            "reqd": 1,
        },
        {
            "fieldname": "tree_details",
            "fieldtype": "Section Break",
            "label": "Tree Details",
            "insert_after": "accounts",
            "hidden": 1,
        },
        {
            "fieldname": "lft",
            "fieldtype": "Int",
            "label": "lft",
            "insert_after": "tree_details",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            "search_index": 1,
        },
        {
            "fieldname": "rgt",
            "fieldtype": "Int",
            "label": "rgt",
            "insert_after": "lft",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
            "search_index": 1,
        },
        {
            "fieldname": "old_parent",
            "fieldtype": "Data",
            "label": "Old Parent",
            "insert_after": "rgt",
            "hidden": 1,
            "read_only": 1,
            "no_copy": 1,
            "print_hide": 1,
        },
    ]

    for df in fields_to_create:
        if not frappe.db.exists(
            "Custom Field", {"dt": "Asset Category", "fieldname": df["fieldname"]}
        ):
            create_custom_field("Asset Category", df)

    _upsert_property_setter("Asset Category", None, "is_tree", "1", "Check", for_doctype=True)
    _upsert_property_setter(
        "Asset Category",
        None,
        "nsm_parent_field",
        "parent_asset_category",
        "Data",
        for_doctype=True,
    )
    _upsert_property_setter("Asset Category", "accounts", "reqd", "0", "Check")

    field_order = [
        "asset_category_name",
        "parent_asset_category",
        "column_break_3",
        "is_group",
        "depreciation_options",
        "enable_cwip_accounting",
        "non_depreciable_category",
        "finance_book_detail",
        "finance_books",
        "section_break_2",
        "accounts",
        "tree_details",
        "lft",
        "rgt",
        "old_parent",
    ]
    _upsert_property_setter(
        "Asset Category",
        None,
        "field_order",
        json.dumps(field_order),
        "Data",
        for_doctype=True,
    )

    _add_lft_rgt_index()


def _upsert_property_setter(
    doctype, fieldname, property_name, value, property_type, for_doctype=False
):
    filters = {
        "doc_type": doctype,
        "property": property_name,
    }
    if fieldname:
        filters["field_name"] = fieldname

    existing = frappe.db.get_value("Property Setter", filters, "name")

    if existing:
        frappe.db.set_value("Property Setter", existing, "value", value, update_modified=False)
        frappe.db.set_value(
            "Property Setter", existing, "property_type", property_type, update_modified=False
        )
        frappe.db.set_value(
            "Property Setter",
            existing,
            "doctype_or_field",
            "DocType" if for_doctype else "DocField",
            update_modified=False,
        )
        frappe.clear_cache(doctype=doctype)
        return

    make_property_setter(
        doctype,
        fieldname,
        property_name,
        value,
        property_type,
        for_doctype=for_doctype,
    )


def _add_lft_rgt_index():
    indexes = frappe.db.sql("SHOW INDEX FROM `tabAsset Category`", as_dict=True)
    existing_columns = {row.Column_name for row in indexes}
    if {"lft", "rgt"}.issubset(existing_columns):
        return

    frappe.db.add_index("Asset Category", ["lft", "rgt"])
