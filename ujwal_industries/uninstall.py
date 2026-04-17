import frappe

# Every custom field created by this app — keyed by (doctype, fieldname).
# Update this list whenever a new patch adds a custom field.
_CUSTOM_FIELDS: list[tuple[str, str]] = [
    # install.py — Stock Settings
    ("Stock Settings", "ins_tab"),
    ("Stock Settings", "ins_section"),
    ("Stock Settings", "applicable_naming_series"),
    ("Stock Settings", "item_naming_series"),
    # install.py — Buying Settings
    ("Buying Settings", "ins_tab"),
    ("Buying Settings", "ins_section"),
    ("Buying Settings", "applicable_customer_naming_series"),
    ("Buying Settings", "customer_naming_series"),
    ("Buying Settings", "applicable_supplier_naming_series"),
    ("Buying Settings", "supplier_naming_series"),
    # create_subcontracting_supplier_fields
    ("Item", "custom_subcontracting_suppliers_section"),
    ("Item", "custom_subcontracting_suppliers"),
    # custom_fields/manufacturing_settings + shift_multiselect
    ("Manufacturing Settings", "production_plan_section"),
    ("Manufacturing Settings", "allow_backdated_planned_start_date"),
    ("Manufacturing Settings", "enable_shift_wise_scheduling"),
    ("Manufacturing Settings", "default_shift_type"),
    # custom_fields/production_plan_item
    ("Production Plan Item", "custom_planned_end_date"),
    # custom_fields/pp_item_shift_csv
    ("Production Plan Item", "custom_shift_types_csv"),
    ("Production Plan Sub Assembly Item", "custom_shift_types_csv"),
    # custom_fields/asset
    ("Asset", "tool_type"),
    # custom_fields/asset_category
    ("Asset Category", "parent_asset_category"),
    ("Asset Category", "is_group"),
    ("Asset Category", "tree_details"),
    ("Asset Category", "lft"),
    ("Asset Category", "rgt"),
    ("Asset Category", "old_parent"),
    # custom_fields/serial_no
    ("Serial No", "source_document_section"),
    ("Serial No", "reference_doctype"),
    ("Serial No", "column_break_source_doc"),
    ("Serial No", "reference_name"),
    ("Serial No", "posting_date"),
    # custom_fields/bom_operation
    ("BOM Operation", "custom_cascade_complete_previous"),
]

# Property Setters created by this app — keyed by (doc_type, field_name, property).
# field_name is None for DocType-level property setters.
_PROPERTY_SETTERS: list[tuple[str, str | None, str]] = [
    ("Asset Category", None, "is_tree"),
    ("Asset Category", None, "nsm_parent_field"),
    ("Asset Category", None, "field_order"),
    ("Asset Category", "accounts", "reqd"),
    ("Sales Order", "order_type", "options"),
]


def after_uninstall():
    _delete_custom_fields()
    _delete_property_setters()
    frappe.db.commit()


def _delete_custom_fields():
    for dt, fieldname in _CUSTOM_FIELDS:
        name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "name")
        if name:
            frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
            print(f"  Deleted Custom Field: {dt}.{fieldname}")


def _delete_property_setters():
    for doc_type, field_name, prop in _PROPERTY_SETTERS:
        filters = {"doc_type": doc_type, "property": prop}
        if field_name:
            filters["field_name"] = field_name
        name = frappe.db.get_value("Property Setter", filters, "name")
        if name:
            frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)
            print(f"  Deleted Property Setter: {doc_type}.{field_name or '*'}.{prop}")
