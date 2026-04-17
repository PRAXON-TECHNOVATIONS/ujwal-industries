import json

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.controllers.accounts_controller import update_child_qty_rate as erpnext_update_child_qty_rate


@frappe.whitelist()
def update_child_qty_rate(parent_doctype, trans_items, parent_doctype_name, child_docname="items"):
	if parent_doctype == "Sales Order":
		_validate_sales_order_update_items_qty_lock(parent_doctype_name, trans_items)

	return erpnext_update_child_qty_rate(
		parent_doctype=parent_doctype,
		trans_items=trans_items,
		parent_doctype_name=parent_doctype_name,
		child_docname=child_docname,
	)


def _validate_sales_order_update_items_qty_lock(sales_order_name, trans_items):
	sales_order = frappe.get_doc("Sales Order", sales_order_name)
	existing_items = {row.name: row for row in sales_order.get("items", [])}
	incoming_items = json.loads(trans_items)

	changed_rows = []
	remaining_existing = set(existing_items.keys())

	for row in incoming_items:
		docname = row.get("docname")
		qty = flt(row.get("qty"))

		if not docname:
			# New rows are allowed. Only rows already covered by production planning are locked.
			continue

		existing_row = existing_items.get(docname)
		if not existing_row:
			continue

		remaining_existing.discard(docname)
		if flt(existing_row.qty) != qty:
			changed_rows.append(
				{
					"row_idx": existing_row.idx,
					"item_code": existing_row.item_code,
					"old_qty": existing_row.qty,
					"new_qty": qty,
					"production_plan_qty": existing_row.production_plan_qty,
					"is_new_row": False,
				}
			)

	for docname in remaining_existing:
		existing_row = existing_items[docname]
		changed_rows.append(
			{
				"row_idx": existing_row.idx,
				"item_code": existing_row.item_code,
				"old_qty": existing_row.qty,
				"new_qty": 0,
				"production_plan_qty": existing_row.production_plan_qty,
				"is_new_row": False,
			}
		)

	if not changed_rows:
		return

	linked_plans_by_item = _get_linked_production_plans(
		sales_order_name, [row.name for row in sales_order.get("items", []) if flt(row.production_plan_qty) > 0]
	)

	locked_changes = []
	for row in changed_rows:
		if flt(row["production_plan_qty"]) > 0:
			linked_plans = ", ".join(linked_plans_by_item.get(row["item_code"], []))
			locked_changes.append(
				_("Row #{0} Item {1} qty cannot be changed from {2} to {3} because a Production Plan is linked against : {4}.").format(
					row["row_idx"],
					row["item_code"] or _("Unknown Item"),
					frappe.format_value(row["old_qty"], {"fieldtype": "Float"}),
					frappe.format_value(row["new_qty"], {"fieldtype": "Float"}),
					linked_plans or _("Production Plan linked"),
				)
			)

	if locked_changes:
		frappe.throw("<br>".join(locked_changes))


def _get_linked_production_plans(sales_order_name, sales_order_items):
	if not sales_order_items:
		return {}

	placeholders = ", ".join(["%s"] * len(sales_order_items))
	rows = frappe.db.sql(
		f"""
		SELECT
			ppi.sales_order_item,
			ppi.item_code,
			pp.name AS production_plan
		FROM `tabProduction Plan Item` ppi
		INNER JOIN `tabProduction Plan` pp ON pp.name = ppi.parent
		WHERE pp.docstatus = 1
			AND ppi.sales_order = %s
			AND ppi.sales_order_item IN ({placeholders})
		""",
		(sales_order_name, *sales_order_items),
		as_dict=True,
	)

	plans_by_item = {}
	for row in rows:
		plans_by_item.setdefault(row.item_code, set()).add(row.production_plan)

	return {item_code: sorted(plan_names) for item_code, plan_names in plans_by_item.items()}
