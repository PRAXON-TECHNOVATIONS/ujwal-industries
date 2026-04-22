import frappe
from frappe import _
from frappe.utils import flt


def prevent_qty_change_when_production_plan_exists(doc, method=None):
	previous = doc.get_doc_before_save()
	if not previous:
		return

	previous_items = {row.name: row for row in previous.get("items", [])}
	changed_rows = []

	for row in doc.get("items", []):
		old_row = previous_items.pop(row.name, None)
		if not old_row:
			continue

		if flt(row.qty) != flt(old_row.qty):
			changed_rows.append(
				{
					"row_idx": row.idx,
					"item_code": row.item_code,
					"sales_order_item": row.name,
					"old_qty": old_row.qty,
					"new_qty": row.qty,
					"production_plan_qty": old_row.production_plan_qty,
				}
			)

	for old_row in previous_items.values():
		changed_rows.append(
			{
				"row_idx": old_row.idx,
				"item_code": old_row.item_code,
				"sales_order_item": old_row.name,
				"old_qty": old_row.qty,
				"new_qty": 0,
				"production_plan_qty": old_row.production_plan_qty,
			}
		)

	if not changed_rows:
		return

	locked_changes = []
	for row in changed_rows:
		if flt(row.get("production_plan_qty")) <= 0:
			continue

		locked_changes.append(
			_("Row #{0} ({1}): qty cannot be changed from {2} to {3} because submitted Production Plan qty is {4}. Cancel the linked Production Plan first.").format(
				row["row_idx"],
				row["item_code"] or row["sales_order_item"],
				frappe.format_value(row["old_qty"], {"fieldtype": "Float"}),
				frappe.format_value(row["new_qty"], {"fieldtype": "Float"}),
				frappe.format_value(row["production_plan_qty"], {"fieldtype": "Float"}),
			)
		)

	if locked_changes:
		frappe.throw(
			_("Sales Order qty cannot be updated while Production Plan is active. Cancel the linked Production Plan first if you need to change qty.<br><br>{0}").format(
				"<br>".join(locked_changes)
			)
		)
