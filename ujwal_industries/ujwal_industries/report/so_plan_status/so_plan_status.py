# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

"""
How much of each Sales Order line is planned, and by which Bulk PP / Production Plan —
the same numbers the Bulk PP item picker uses to lock a line. One row per SO line,
expandable into one row per plan holding it.
"""

import frappe
from frappe import _
from frappe.utils import flt

from ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan import (
	_get_so_item_basis_qty,
	_get_so_item_plan_map,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"fieldname": "sales_order", "label": _("Sales Order"), "fieldtype": "Link", "options": "Sales Order", "width": 170},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 140},
		{"fieldname": "delivery_date", "label": _("Delivery Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 110},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "qty", "label": _("SO Qty"), "fieldtype": "Float", "width": 110},
		{"fieldname": "planned_qty", "label": _("Planned Qty"), "fieldtype": "Float", "width": 110},
		{"fieldname": "remaining_qty", "label": _("Left to Plan"), "fieldtype": "Float", "width": 110},
		{"fieldname": "plan_status", "label": _("Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "plan_doctype", "label": _("Plan Type"), "fieldtype": "Data", "hidden": 1},
		{"fieldname": "plan", "label": _("Planned In"), "fieldtype": "Dynamic Link", "options": "plan_doctype", "width": 190},
	]


def get_data(filters):
	conditions = ["so.docstatus = 1", "so.status NOT IN ('Stopped', 'Closed')"]
	for field, cond in (
		("company", "so.company = %(company)s"),
		("customer", "so.customer = %(customer)s"),
		("sales_order", "so.name = %(sales_order)s"),
		("item_code", "soi.item_code = %(item_code)s"),
		("from_date", "so.transaction_date >= %(from_date)s"),
		("to_date", "so.transaction_date <= %(to_date)s"),
		("from_delivery_date", "soi.delivery_date >= %(from_delivery_date)s"),
		("to_delivery_date", "soi.delivery_date <= %(to_delivery_date)s"),
	):
		if filters.get(field):
			conditions.append(cond)

	lines = frappe.db.sql(
		f"""
		SELECT
			soi.name AS sales_order_item, so.name AS sales_order, so.customer,
			soi.delivery_date, soi.item_code, soi.item_name
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE {" AND ".join(conditions)}
		ORDER BY soi.delivery_date, so.name, soi.idx
		""",
		filters,
		as_dict=True,
	)

	names = [line.sales_order_item for line in lines]
	basis_map = _get_so_item_basis_qty(names)
	plan_map = _get_so_item_plan_map(names)
	plan_docstatus = _get_plan_docstatus(plan_map)

	data = []
	for line in lines:
		qty = flt((basis_map.get(line.sales_order_item) or {}).get("qty"))
		planned = plan_map.get(line.sales_order_item) or {}
		planned_qty = flt(planned.get("planned_qty"))
		remaining = max(qty - planned_qty, 0.0)
		status = (
			_("Fully Planned") if planned_qty and remaining <= 0.001
			else _("Partly Planned") if planned_qty
			else _("Not Planned")
		)
		if filters.get("plan_status") and status != _(filters.plan_status):
			continue

		data.append({
			**line,
			"qty": qty,
			"planned_qty": planned_qty,
			"remaining_qty": remaining,
			"plan_status": status,
			"indent": 0,
		})
		for doctype, name in planned.get("planned_refs") or []:
			data.append({
				"plan_doctype": doctype,
				"plan": name,
				"planned_qty": planned["qty_by_ref"].get(name),
				"plan_status": {0: _("Draft"), 1: _("Submitted")}.get(plan_docstatus.get((doctype, name)), ""),
				"indent": 1,
			})

	return data


def _get_plan_docstatus(plan_map) -> dict:
	refs = {ref for entry in plan_map.values() for ref in entry.get("planned_refs") or []}
	result = {}
	for doctype in {dt for dt, _name in refs}:
		for row in frappe.get_all(
			doctype,
			filters={"name": ["in", [name for dt, name in refs if dt == doctype]]},
			fields=["name", "docstatus"],
		):
			result[(doctype, row.name)] = row.docstatus
	return result
