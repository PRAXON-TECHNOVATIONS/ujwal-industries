import frappe


def execute():
    """
    Add custom_shift_types_csv (Small Text) to:
      - Production Plan Item        (po_items)
      - Production Plan Sub Assembly Item (sub_assembly_items)

    Stores the comma-separated Shift Type names configured per row in the
    Bulk PP planner, so the Manage-Dates cascade can use the correct
    holiday list for each row's shift.
    """
    fields = [
        {
            "dt": "Production Plan Item",
            "fieldname": "custom_shift_types_csv",
            "fieldtype": "Small Text",
            "label": "Shift Types CSV",
            "insert_after": "custom_mfg_days",
            "hidden": 1,
            "description": "Comma-separated Shift Type names used during parallel planning.",
        },
        {
            "dt": "Production Plan Sub Assembly Item",
            "fieldname": "custom_shift_types_csv",
            "fieldtype": "Small Text",
            "label": "Shift Types CSV",
            "insert_after": "custom_mfg_days",
            "hidden": 1,
            "description": "Comma-separated Shift Type names used during parallel planning.",
        },
    ]

    for fdef in fields:
        if frappe.db.exists("Custom Field", {"dt": fdef["dt"], "fieldname": fdef["fieldname"]}):
            continue
        frappe.get_doc({"doctype": "Custom Field", **fdef}).insert()

    frappe.db.commit()
