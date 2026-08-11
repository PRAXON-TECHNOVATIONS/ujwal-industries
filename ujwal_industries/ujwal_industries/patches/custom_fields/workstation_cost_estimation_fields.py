import frappe


def create_fields():
    fields = [
        {
            "dt": "Workstation",
            "fieldname": "custom_cost_estimation_tab",
            "fieldtype": "Tab Break",
            "label": "Cost Estimation",
            "insert_after": "connections_tab",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_machine_emi_per_day",
            "fieldtype": "Currency",
            "label": "Machine EMI per Day",
            "insert_after": "custom_cost_estimation_tab",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_wages_per_day",
            "fieldtype": "Currency",
            "label": "Wages per Day",
            "insert_after": "custom_machine_emi_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_electricity_per_day",
            "fieldtype": "Currency",
            "label": "Electricity Charges per Day",
            "insert_after": "custom_wages_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_cost_column_break_1",
            "fieldtype": "Column Break",
            "insert_after": "custom_electricity_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_factory_expenses_per_day",
            "fieldtype": "Currency",
            "label": "Factory Expenses per Day",
            "insert_after": "custom_cost_column_break_1",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_finance_cost_per_day",
            "fieldtype": "Currency",
            "label": "Finance Cost per Day",
            "insert_after": "custom_factory_expenses_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_admin_cost_per_day",
            "fieldtype": "Currency",
            "label": "Admin Cost per Day",
            "insert_after": "custom_finance_cost_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_selling_dist_cost_per_day",
            "fieldtype": "Currency",
            "label": "Selling & Distribution Cost per Day",
            "insert_after": "custom_admin_cost_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_cost_section_break_1",
            "fieldtype": "Section Break",
            "insert_after": "custom_selling_dist_cost_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_total_cost_per_day",
            "fieldtype": "Currency",
            "label": "Total Cost per Day",
            "read_only": 1,
            "insert_after": "custom_cost_section_break_1",
            "description": "Sum of EMI, wages, electricity, factory, finance, admin and selling costs per day.",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_shift_hours",
            "fieldtype": "Float",
            "label": "Shift Hours",
            "default": "8",
            "insert_after": "custom_total_cost_per_day",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_cost_column_break_2",
            "fieldtype": "Column Break",
            "insert_after": "custom_shift_hours",
        },
        {
            "dt": "Workstation",
            "fieldname": "custom_cost_per_min",
            "fieldtype": "Currency",
            "label": "Cost per Min (Shift Rate)",
            "read_only": 1,
            "precision": "4",
            "insert_after": "custom_cost_column_break_2",
            "description": "Total Cost per Day / 60 / Shift Hours. Used as the default Shift Rate per Min on Cost Estimation.",
        },
    ]

    for field in fields:
        if frappe.db.exists("Custom Field", {"dt": field["dt"], "fieldname": field["fieldname"]}):
            continue
        frappe.get_doc({"doctype": "Custom Field", **field}).insert()

    frappe.db.commit()


def execute():
    create_fields()
