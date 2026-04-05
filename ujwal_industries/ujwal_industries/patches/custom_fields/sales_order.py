import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def create_fields():
    meta = frappe.get_meta("Sales Order")
    field = meta.get_field("order_type")

    if not field:
        return

    current_options = field.options or ""
    options = [option.strip() for option in current_options.split("\n") if option.strip()]

    if "Forecast" in options:
        return

    options.append("Forecast")
    _upsert_property_setter(
        "Sales Order",
        "order_type",
        "options",
        "\n".join(options),
        "Text",
    )


def _upsert_property_setter(doctype, fieldname, property_name, value, property_type):
    filters = {
        "doc_type": doctype,
        "field_name": fieldname,
        "property": property_name,
    }

    existing = frappe.db.get_value("Property Setter", filters, "name")

    if existing:
        frappe.db.set_value("Property Setter", existing, "value", value, update_modified=False)
        frappe.db.set_value(
            "Property Setter", existing, "property_type", property_type, update_modified=False
        )
        frappe.db.set_value(
            "Property Setter", existing, "doctype_or_field", "DocField", update_modified=False
        )
        frappe.clear_cache(doctype=doctype)
        return

    make_property_setter(
        doctype,
        fieldname,
        property_name,
        value,
        property_type,
    )
