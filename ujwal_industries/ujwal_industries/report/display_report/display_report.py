# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Job Card ID"), "fieldname": "name", "fieldtype": "Link", "options": "Job Card", "width": 150},
		{"label": _("Work Order"), "fieldname": "work_order", "fieldtype": "Link", "options": "Work Order", "width": 200},
		{"label": _("Production Item"), "fieldname": "production_item", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Production Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 180},
		{"label": _("Workstation"), "fieldname": "workstation", "fieldtype": "Link", "options": "Workstation", "width": 130},
		{"label": _("Workstation Name"), "fieldname": "workstation_name", "fieldtype": "Data", "width": 160},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
		{"label": _("Planned Start Date"), "fieldname": "expected_start_date", "fieldtype": "Datetime", "width": 200},
		{"label": _("Planned End Date"), "fieldname": "expected_end_date", "fieldtype": "Datetime", "width": 200},
	]


def get_conditions(filters):
	filters = filters or {}
	conditions = ["jc.status not in ('Completed', 'Cancelled')"]
	values = {}

	if filters.get("company"):
		conditions.append("jc.company = %(company)s")
		values["company"] = filters.get("company")

	if filters.get("work_order"):
		conditions.append("jc.work_order = %(work_order)s")
		values["work_order"] = filters.get("work_order")

	if filters.get("workstation"):
		conditions.append("jc.workstation = %(workstation)s")
		values["workstation"] = filters.get("workstation")

	if filters.get("production_item"):
		conditions.append("jc.production_item = %(production_item)s")
		values["production_item"] = filters.get("production_item")

	if filters.get("status"):
		conditions.append("jc.status = %(status)s")
		values["status"] = filters.get("status")

	if filters.get("from_date"):
		conditions.append("jc.expected_start_date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")

	if filters.get("to_date"):
		conditions.append("jc.expected_end_date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")

	condition_str = ("where " + " and ".join(conditions)) if conditions else ""
	return condition_str, values


def get_data(filters):
	condition_str, values = get_conditions(filters)

	data = frappe.db.sql(
		f"""
		select
			jc.name as name,
			jc.work_order as work_order,
			jc.production_item as production_item,
			item.item_name as item_name,
			jc.workstation as workstation,
			ws.custom_asset as workstation_name,
			jc.status as status,
			jc.expected_start_date as expected_start_date,
			jc.expected_end_date as expected_end_date
		from `tabJob Card` jc
		left join `tabItem` item on item.name = jc.production_item
		left join `tabWorkstation` ws on ws.name = jc.workstation
		{condition_str}
		order by jc.expected_start_date desc
		""",
		values,
		as_dict=1,
	)

	return data