"""Fix BOM-200122-001's RM row (item 100118) qty to match stock_qty.

This row had qty=28.73 but stock_qty=2.21 with conversion_factor=1.0 — since
conversion_factor is 1, qty and stock_qty must be equal. stock_qty (2.21) is
the correct value (Cost Estimation reads stock_qty and, scaled through
BOM-300189-001's own consumption ratio, already correctly produces 28.73 Kg
per 100 finished pieces — matching the BOM tree's higher-level display). The
qty field itself (what the BOM tree shows directly at this level) was stale
at 28.73 and needs correcting to 2.21 to match.

Corrects:
  - BOM-200122-001's BOM Item row for 100118: qty -> 2.21 (was 28.73)
"""

import frappe

BOM_NAME = "BOM-200122-001"
ITEM_CODE = "100118"
CORRECT_QTY = 2.21


def execute():
	row_name = frappe.db.get_value(
		"BOM Item", {"parent": BOM_NAME, "item_code": ITEM_CODE}, "name"
	)
	if not row_name:
		return

	current_qty = frappe.db.get_value("BOM Item", row_name, "qty")
	if current_qty != CORRECT_QTY:
		frappe.db.set_value("BOM Item", row_name, "qty", CORRECT_QTY, update_modified=False)
		frappe.db.commit()
		frappe.logger().info(
			f"fix_bom_200122_item_qty: corrected {BOM_NAME} item {ITEM_CODE} qty "
			f"{current_qty} -> {CORRECT_QTY}"
		)
