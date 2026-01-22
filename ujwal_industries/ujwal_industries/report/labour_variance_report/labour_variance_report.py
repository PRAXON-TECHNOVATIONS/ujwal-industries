# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, time_diff_in_seconds


def execute(filters=None):
	"""Execute the Labour Variance Report.

	This report shows Job Card labor variance in a tree structure:
	- Parent rows: Job Card summary with total variance
	- Child rows: Individual employee time logs with their variance

	Variance = Actual Time - Expected Time
	Positive variance means overtime (actual > expected)
	Negative variance means undertime (actual < expected)
	"""
	if not filters:
		filters = frappe._dict()

	columns = get_columns()
	data = get_data(filters)

	return columns, data


def get_columns():
	"""Define report columns."""
	columns = [
		{
			"fieldname": "job_card",
			"label": _("Job Card"),
			"fieldtype": "Link",
			"options": "Job Card",
			"width": 150,
		},
		{
			"fieldname": "employee",
			"label": _("Employee"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": 150,
		},
		{
			"fieldname": "work_order",
			"label": _("Work Order"),
			"fieldtype": "Link",
			"options": "Work Order",
			"width": 150,
		},
		{
			"fieldname": "operation",
			"label": _("Operation"),
			"fieldtype": "Link",
			"options": "Operation",
			"width": 120,
		},
		{
			"fieldname": "workstation",
			"label": _("Workstation"),
			"fieldtype": "Link",
			"options": "Workstation",
			"width": 120,
		},
		{
			"fieldname": "production_item",
			"label": _("Production Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
		},
		{
			"fieldname": "qty_to_manufacture",
			"label": _("Qty To Manufacture"),
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"fieldname": "completed_qty",
			"label": _("Completed Qty"),
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"fieldname": "expected_time_mins",
			"label": _("Expected Time (Mins)"),
			"fieldtype": "Float",
			"width": 140,
		},
		{
			"fieldname": "actual_time_mins",
			"label": _("Actual Time (Mins)"),
			"fieldtype": "Float",
			"width": 140,
		},
		{
			"fieldname": "variance_mins",
			"label": _("Variance (Mins)"),
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"fieldname": "variance_percent",
			"label": _("Variance (%)"),
			"fieldtype": "Percent",
			"width": 120,
		},
		{
			"fieldname": "status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "posting_date",
			"label": _("Posting Date"),
			"fieldtype": "Date",
			"width": 100,
		},
	]
	return columns


def get_data(filters):
	"""Get job card data with employee time logs in tree structure."""
	conditions = get_conditions(filters)

	# Get Job Card data
	job_cards = frappe.db.sql(
		f"""
		SELECT
			jc.name as job_card,
			jc.work_order,
			jc.operation,
			jc.workstation,
			jc.production_item,
			jc.for_quantity as qty_to_manufacture,
			jc.total_completed_qty as completed_qty,
			jc.time_required as expected_time_mins,
			jc.total_time_in_mins as actual_time_mins,
			jc.status,
			jc.posting_date,
			jc.company
		FROM
			`tabJob Card` jc
		WHERE
			jc.docstatus < 2
			{conditions}
		ORDER BY
			jc.posting_date DESC, jc.name DESC
		""",
		filters,
		as_dict=True,
	)

	if not job_cards:
		return []

	# Get all time logs for these job cards
	job_card_names = [jc.job_card for jc in job_cards]
	time_logs = get_time_logs(job_card_names)

	# Build tree structure data
	data = []
	for job_card in job_cards:
		# Calculate variance for parent row
		expected = flt(job_card.expected_time_mins)
		actual = flt(job_card.actual_time_mins)
		variance = actual - expected
		variance_percent = (variance / expected * 100) if expected > 0 else 0

		# Parent row - Job Card summary
		parent_row = {
			"indent": 0,
			"job_card": job_card.job_card,
			"employee": None,  # No specific employee for parent row
			"work_order": job_card.work_order,
			"operation": job_card.operation,
			"workstation": job_card.workstation,
			"production_item": job_card.production_item,
			"qty_to_manufacture": job_card.qty_to_manufacture,
			"completed_qty": job_card.completed_qty,
			"expected_time_mins": expected,
			"actual_time_mins": actual,
			"variance_mins": variance,
			"variance_percent": variance_percent,
			"status": job_card.status,
			"posting_date": job_card.posting_date,
		}

		data.append(parent_row)

		# Child rows - Employee time logs
		job_card_logs = time_logs.get(job_card.job_card, [])
		for log in job_card_logs:
			# For employee rows, variance is calculated differently
			# We compare their actual time vs proportional expected time
			# Proportional expected = (employee_qty / total_qty) * expected_time
			proportional_expected = 0
			if job_card.completed_qty > 0 and expected > 0:
				proportional_expected = (flt(log.completed_qty) / flt(job_card.completed_qty)) * expected

			employee_actual = flt(log.time_in_mins)
			employee_variance = employee_actual - proportional_expected
			employee_variance_percent = (
				(employee_variance / proportional_expected * 100) if proportional_expected > 0 else 0
			)

			child_row = {
				"indent": 1,
				"job_card": job_card.job_card,
				"employee": log.employee,
				"work_order": None,  # Don't repeat parent info in child rows
				"operation": None,
				"workstation": None,
				"production_item": None,
				"qty_to_manufacture": None,
				"completed_qty": log.completed_qty,
				"expected_time_mins": proportional_expected,
				"actual_time_mins": employee_actual,
				"variance_mins": employee_variance,
				"variance_percent": employee_variance_percent,
				"status": None,
				"posting_date": None,
			}
			data.append(child_row)

	return data


def get_conditions(filters):
	"""Build SQL WHERE conditions from filters."""
	conditions = []

	if filters.get("job_card"):
		conditions.append("jc.name = %(job_card)s")

	if filters.get("work_order"):
		conditions.append("jc.work_order = %(work_order)s")

	if filters.get("operation"):
		conditions.append("jc.operation = %(operation)s")

	if filters.get("workstation"):
		conditions.append("jc.workstation = %(workstation)s")

	if filters.get("production_item"):
		conditions.append("jc.production_item = %(production_item)s")

	if filters.get("company"):
		conditions.append("jc.company = %(company)s")

	if filters.get("from_date"):
		conditions.append("jc.posting_date >= %(from_date)s")

	if filters.get("to_date"):
		conditions.append("jc.posting_date <= %(to_date)s")

	if filters.get("status"):
		conditions.append("jc.status = %(status)s")

	return " AND " + " AND ".join(conditions) if conditions else ""


def get_time_logs(job_card_names):
	"""Get all time logs for the given job cards, grouped by job card."""
	if not job_card_names:
		return {}

	time_logs = frappe.db.sql(
		"""
		SELECT
			parent as job_card,
			employee,
			from_time,
			to_time,
			time_in_mins,
			completed_qty
		FROM
			`tabJob Card Time Log`
		WHERE
			parent IN %(job_cards)s
			AND employee IS NOT NULL
		ORDER BY
			parent, from_time
		""",
		{"job_cards": job_card_names},
		as_dict=True,
	)

	# Group by job card
	logs_by_job_card = {}
	for log in time_logs:
		logs_by_job_card.setdefault(log.job_card, []).append(log)

	return logs_by_job_card
