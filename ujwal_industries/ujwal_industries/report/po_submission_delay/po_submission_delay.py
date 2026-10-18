# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

"""
System-generated Purchase Orders (from Bulk PP / Production Plan): how long each one sat
in draft before it was submitted, and which drafts are still waiting.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, time_diff_in_hours


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "purchase_order", "label": _("Purchase Order"), "fieldtype": "Link", "options": "Purchase Order", "width": 140},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "supplier", "label": _("Supplier"), "fieldtype": "Link", "options": "Supplier", "width": 110},
		{"fieldname": "supplier_name", "label": _("Supplier Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "generated_on", "label": _("Generated On"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "submitted_on", "label": _("Submitted On"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "delay_days", "label": _("Delay (Days)"), "fieldtype": "Float", "precision": 1, "width": 100},
		{"fieldname": "submitted_by", "label": _("Submitted By"), "fieldtype": "Link", "options": "User", "width": 180},
		{"fieldname": "grand_total", "label": _("Grand Total"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "production_plan", "label": _("Production Plan"), "fieldtype": "Link", "options": "Production Plan", "width": 150},
		{"fieldname": "bulk_pp", "label": _("Bulk PP"), "fieldtype": "Link", "options": "Bulk Pre Production Plan", "width": 160},
	]


def get_data(filters):
	conditions = ["po.docstatus < 2"]
	if filters.company:
		conditions.append("po.company = %(company)s")
	if filters.supplier:
		conditions.append("po.supplier = %(supplier)s")
	if filters.submitted_by:
		conditions.append("po.custom_submitted_by = %(submitted_by)s")
	if filters.from_date:
		conditions.append("DATE(COALESCE(po.custom_generated_on, po.creation)) >= %(from_date)s")
	if filters.to_date:
		conditions.append("DATE(COALESCE(po.custom_generated_on, po.creation)) <= %(to_date)s")
	if filters.status == "Pending":
		conditions.append("po.docstatus = 0")
	elif filters.status == "Submitted":
		conditions.append("po.docstatus = 1")

	rows = frappe.db.sql(
		f"""
		SELECT
			po.name AS purchase_order, po.docstatus, po.supplier, po.supplier_name,
			COALESCE(po.custom_generated_on, po.creation) AS generated_on,
			po.custom_submitted_on AS submitted_on, po.custom_submitted_by AS submitted_by,
			po.custom_submission_delay_days AS delay_days, po.grand_total,
			MIN(poi.production_plan) AS production_plan, pp.custom_bulk_pre_production_plan AS bulk_pp
		FROM `tabPurchase Order` po
		INNER JOIN `tabPurchase Order Item` poi
			ON poi.parent = po.name AND COALESCE(poi.production_plan, '') != ''
		LEFT JOIN `tabProduction Plan` pp ON pp.name = poi.production_plan
		WHERE {" AND ".join(conditions)}
		GROUP BY po.name
		ORDER BY generated_on DESC
		""",
		filters,
		as_dict=True,
	)

	now = now_datetime()
	min_delay = flt(filters.min_delay_days)
	data = []
	for row in rows:
		if row.docstatus == 0:
			row.status = _("Pending")
			row.delay_days = round(max(time_diff_in_hours(now, row.generated_on), 0) / 24, 1)
		else:
			row.status = _("Submitted")
		if min_delay and flt(row.delay_days) < min_delay:
			continue
		data.append(row)
	return data
