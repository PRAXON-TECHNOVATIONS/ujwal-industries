# Copyright (c) 2026, Ujjwal Aggrawal and contributors
# For license information, please see license.txt

# import frappe

# def execute(filters=None):
# 	columns, data = [], []
# 	return columns, data

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "label": _("Purchase Receipt"),
            "fieldname": "purchase_receipt",
            "fieldtype": "Link",
            "options": "Purchase Receipt",
            "width": 200,
        },
        {
            "label": _("Item Code"),
            "fieldname": "item_code",
            "fieldtype": "Link",
            "options": "Item",
            "width": 180,
        },
        {
            "label": _("Qty"),
            "fieldname": "qty",
            "fieldtype": "Float",
            "width": 100,
        },
        {
            "label": _("Sample Size"),
            "fieldname": "sample_size",
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "label": _("Actual Processing Days"),
            "fieldname": "actual_processing_days",
            "fieldtype": "Float",
            "width": 200,
        },
        {
            "label": _("Expected Processing Days"),
            "fieldname": "expected_processing_days",
            "fieldtype": "Float",
            "width": 220,
        },
        {
            "label": _("Delay (Days)"),
            "fieldname": "delay_days",
            "fieldtype": "Float",
            "width": 150,
        },
    ]


def get_data(filters):
    data = []

    conditions = ["pr.docstatus = 1"]

    if filters.get("from_date"):
        conditions.append("pr.posting_date >= %(from_date)s")

    if filters.get("to_date"):
        conditions.append("pr.posting_date <= %(to_date)s")

    if filters.get("purchase_receipt"):
        conditions.append("pr.name = %(purchase_receipt)s")

    condition_str = " AND ".join(conditions)

    prs = frappe.db.sql(
        f"""
        SELECT pr.name
        FROM `tabPurchase Receipt` pr
        WHERE {condition_str}
        ORDER BY pr.posting_date DESC
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
                pri.custom_actual_processing_days AS actual_days,
                it.custom_expected_grn_processing_days AS expected_days,
                (
                    SELECT SUM(qi.sample_size)
                    FROM `tabQuality Inspection` qi
                    WHERE
                        qi.reference_type = 'Purchase Receipt'
                        AND qi.reference_name = pri.parent
                        AND qi.item_code = pri.item_code
                        AND qi.docstatus = 1
                ) AS sample_size
            FROM `tabPurchase Receipt Item` pri
            LEFT JOIN `tabItem` it ON it.name = pri.item_code
            WHERE pri.parent = %s
            """,
            pr.name,
            as_dict=True,
        )

        total_qty = 0
        total_sample = 0
        total_actual = 0
        total_expected = 0

        start_index = len(data)

        for it in items:
            qty = flt(it.qty)
            sample = flt(it.sample_size)
            actual = flt(it.actual_days)
            expected = flt(it.expected_days)
            delay = actual - expected

            total_qty += qty
            total_sample += sample
            total_actual += actual
            total_expected += expected

            # Child row
            data.append({
                "indent": 1,
                "purchase_receipt": pr.name,
                "item_code": it.item_code,
                "qty": qty,
                "sample_size": sample,
                "actual_processing_days": actual,
                "expected_processing_days": expected,
                "delay_days": delay,
            })

        # Parent (collapsed) row – totals
        data.insert(start_index, {
            "indent": 0,
            "purchase_receipt": pr.name,
            "qty": total_qty,
            "sample_size": total_sample,
            "actual_processing_days": total_actual,
            "expected_processing_days": total_expected,
            "delay_days": total_actual - total_expected,
        })

    return data
