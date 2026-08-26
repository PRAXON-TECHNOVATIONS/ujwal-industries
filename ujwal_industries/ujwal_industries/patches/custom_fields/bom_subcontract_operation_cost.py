import frappe


def create_fields():
    fields = [
        {
            "dt": "BOM",
            "fieldname": "custom_subcontract_operation_cost",
            "fieldtype": "Float",
            "label": "Subcontract Operation Cost",
            "precision": "3",
            "read_only": 1,
            "allow_on_submit": 1,
            "insert_after": "operating_cost",
            "description": (
                "This BOM's own item's default Subcontract operation Rate per Pc "
                "(from the Item master), scaled to this BOM's Quantity. Kept in "
                "sync when the item's rate changes, and included in Total Cost — "
                "separate from Operating Cost, which stays in-house-only so Work "
                "Order / Job Card creation is not affected."
            ),
        },
    ]

    for field in fields:
        if frappe.db.exists("Custom Field", {"dt": field["dt"], "fieldname": field["fieldname"]}):
            continue
        frappe.get_doc({"doctype": "Custom Field", **field}).insert()

    frappe.db.commit()


def execute():
    create_fields()
