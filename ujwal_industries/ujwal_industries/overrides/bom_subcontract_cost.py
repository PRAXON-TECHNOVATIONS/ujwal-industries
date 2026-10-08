# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

"""Keeps BOM.custom_subcontract_operation_cost (and Total Cost) in sync with
the default Subcontract rate set on the BOM's own item (Item's Purchasing
tab → Subcontracting Suppliers). Deliberately does NOT touch ERPNext's own
BOM.calculate_cost()/update_cost() — those stay in-house-only, so Work Order
/ Job Card creation is never affected by a subcontracted step. Two separate
paths:

- set_subcontract_operation_cost (BOM validate() hook): safe, additive-only.
  Runs after BOM's own core validate() already computed total_cost, so this
  just adds our field on top, for any normal create/edit/submit of the BOM.

- refresh_subcontract_operation_cost (whitelisted): the "on change of the
  item's default rate, go update whichever BOMs need it" path. Writes
  directly to the DB (works on submitted BOMs) and cascades to every parent
  BOM that consumes this BOM as a component, the same way ERPNext's own
  update_cost() cascades — but scoped to just this addition, not a full
  re-run of core BOM costing.
"""

import frappe
from frappe.utils import flt

from ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation import (
	get_subcontract_operation_row,
)


def compute_subcontract_operation_cost(item_code, company, quantity):
	row = get_subcontract_operation_row(item_code, company=company)
	if not row:
		return 0.0
	return flt(row["rate_per_pc"]) * flt(quantity)


def set_subcontract_operation_cost(doc, method=None):
	cost = compute_subcontract_operation_cost(doc.item, doc.company, doc.quantity)
	doc.custom_subcontract_operation_cost = cost
	doc.total_cost = flt(doc.total_cost) + cost
	if doc.meta.has_field("base_total_cost"):
		doc.base_total_cost = flt(doc.base_total_cost) + cost * flt(doc.conversion_rate or 1)


@frappe.whitelist()
def refresh_subcontract_operation_cost(bom_name, _visited=None):
	_visited = _visited if _visited is not None else set()
	if bom_name in _visited:
		return
	_visited.add(bom_name)

	bom = frappe.db.get_value(
		"BOM",
		bom_name,
		["item", "company", "quantity", "operating_cost", "raw_material_cost", "scrap_material_cost", "docstatus"],
		as_dict=True,
	)
	if not bom or bom.docstatus == 2:
		return

	new_subcontract_cost = compute_subcontract_operation_cost(bom.item, bom.company, bom.quantity)
	new_total_cost = (
		flt(bom.operating_cost) + flt(bom.raw_material_cost) - flt(bom.scrap_material_cost) + new_subcontract_cost
	)

	frappe.db.set_value(
		"BOM",
		bom_name,
		{
			"custom_subcontract_operation_cost": new_subcontract_cost,
			"total_cost": new_total_cost,
		},
		update_modified=False,
	)

	# Cascade: any BOM that consumes this BOM as a component row needs that
	# row's rate/amount (and therefore its own raw material + total cost)
	# refreshed to reflect this BOM's new per-unit cost.
	parent_rows = frappe.get_all(
		"BOM Item",
		filters={"bom_no": bom_name, "docstatus": ["<", 2], "parenttype": "BOM"},
		fields=["name", "parent", "stock_qty"],
	)
	if not parent_rows:
		return

	new_rate = new_total_cost / bom.quantity if bom.quantity else 0

	parents_to_refresh = set()
	for row in parent_rows:
		new_amount = flt(row.stock_qty) * new_rate
		frappe.db.set_value(
			"BOM Item", row.name, {"rate": new_rate, "amount": new_amount}, update_modified=False
		)
		parents_to_refresh.add(row.parent)

	for parent_name in parents_to_refresh:
		parent_rm_cost = (
			frappe.db.sql(
				"""SELECT SUM(amount) FROM `tabBOM Item` WHERE parent=%s AND docstatus < 2""",
				parent_name,
			)[0][0]
			or 0
		)
		frappe.db.set_value("BOM", parent_name, "raw_material_cost", parent_rm_cost, update_modified=False)
		refresh_subcontract_operation_cost(parent_name, _visited=_visited)
