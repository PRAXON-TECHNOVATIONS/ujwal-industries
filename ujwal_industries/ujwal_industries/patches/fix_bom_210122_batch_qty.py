"""Fix BOM-210122-001's batch quantity and its RM row's stale stock_qty.

BOM-210122-001's batch quantity was 1920, inconsistent with what its parent
BOM (BOM-300189-001) actually consumes (200 units of item 210122, i.e. 2 per
finished piece of the parent at the parent's own reference batch of 100).
For BOM-210122-001's own RM row (0.06 Kg of item 100470) to correctly
reproduce the BOM tree's displayed 0.06 Kg when the parent estimate is for
100 pcs, BOM-210122-001's batch quantity must be 2 (matching "2 units of
210122 per parent piece"), not 200 or 1920.

Corrects:
  - BOM-210122-001.quantity: 1920 -> 2
  - its BOM Item row for 100470: stock_qty -> qty * conversion_factor (0.06)
"""

import frappe

BOM_NAME = "BOM-210122-001"
CORRECT_BATCH_QTY = 2


def execute():
	if not frappe.db.exists("BOM", BOM_NAME):
		return

	current_qty = frappe.db.get_value("BOM", BOM_NAME, "quantity")
	if current_qty != CORRECT_BATCH_QTY:
		frappe.db.set_value("BOM", BOM_NAME, "quantity", CORRECT_BATCH_QTY, update_modified=False)

	rows = frappe.get_all(
		"BOM Item",
		filters={"parent": BOM_NAME},
		fields=["name", "qty", "stock_qty", "conversion_factor"],
	)
	for row in rows:
		expected = row.qty * row.conversion_factor
		if row.stock_qty != expected:
			frappe.db.set_value("BOM Item", row.name, "stock_qty", expected, update_modified=False)

	frappe.db.commit()

	frappe.logger().info(
		f"fix_bom_210122_batch_qty: set {BOM_NAME}.quantity to {CORRECT_BATCH_QTY} "
		f"and corrected its BOM Item stock_qty"
	)
