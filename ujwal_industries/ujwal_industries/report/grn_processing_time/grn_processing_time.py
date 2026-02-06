# Copyright (c) 2026, Ujjwal Aggrawal and contributors
# For license information, please see license.txt

# import frappe


# def execute(filters=None):
# 	columns, data = [], []
# 	return columns, data
import frappe
from frappe import _


import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {"label": _("Purchase Receipt"), "fieldname": "purchase_receipt",
         "fieldtype": "Link", "options": "Purchase Receipt", "width": 200},

        {"label": _("Item Code"), "fieldname": "item_code",
         "fieldtype": "Link", "options": "Item", "width": 140},

        {"label": _("Qty"), "fieldname": "qty",
         "fieldtype": "Float", "width": 100},

        {"label": _("Actual Processing Time (Days)"),
         "fieldname": "actual_processing_days",
         "fieldtype": "Float", "width": 240},

        {"label": _("Expected Processing Time (Days)"),
         "fieldname": "expected_processing_days",
         "fieldtype": "Float", "width": 260},

        {"label": _("Delay (Days)"),
         "fieldname": "delay_days",
         "fieldtype": "Float", "width": 160},
    ]


def get_data(filters):
    data = []

    conditions = ["pr.docstatus = 1"]

    if filters.get("from_date"):
        conditions.append("pr.creation >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("pr.creation <= %(to_date)s")
    if filters.get("purchase_receipt"):
        conditions.append("pr.name = %(purchase_receipt)s")

    condition_str = " AND ".join(conditions)

    prs = frappe.db.sql(
        f"""
        SELECT pr.name
        FROM `tabPurchase Receipt` pr
        WHERE {condition_str}
        ORDER BY pr.creation DESC
        """,
        filters,
        as_dict=True,
    )

    for pr in prs:
        items = frappe.db.sql(
            """
            SELECT
                pri.item_code,
                pri.qty,
                pri.custom_actual_processing_days,
                it.custom_expected_grn_processing_days
            FROM `tabPurchase Receipt Item` pri
            LEFT JOIN `tabItem` it ON it.name = pri.item_code
            WHERE pri.parent = %s
            """,
            pr.name,
            as_dict=True,
        )

        total_qty = 0
        total_actual = 0
        total_expected = 0
        total_delay = 0

        for it in items:
            qty = it.qty or 0
            actual_total = it.custom_actual_processing_days or 0
            expected_per_unit = it.custom_expected_grn_processing_days or 0

            expected_total = expected_per_unit * qty
            delay = actual_total - expected_total

            total_qty += qty
            total_actual += actual_total
            total_expected += expected_total
            total_delay += delay

            data.append({
                "indent": 1,
                "purchase_receipt": pr.name,
                "item_code": it.item_code,
                "qty": qty,
                "actual_processing_days": actual_total,
                "expected_processing_days": expected_total,
                "delay_days": delay,
            })

        # Parent PR summary row
        data.insert(len(data) - len(items), {
            "indent": 0,
            "purchase_receipt": pr.name,
            "qty": total_qty,
            "actual_processing_days": total_actual,
            "expected_processing_days": total_expected,
            "delay_days": total_delay,
        })

    return data
