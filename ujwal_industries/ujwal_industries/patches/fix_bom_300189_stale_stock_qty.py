"""Fix stale stock_qty on BOM-300189-001's BOM Item rows.

This BOM's qty was corrected (200122 -> 1300, 210122 -> 200) but the derived
stock_qty column was never recalculated, so it stayed at the old values
(12480, 1920). Since conversion_factor = 1 for both rows, stock_qty should
always equal qty * conversion_factor. Cost Estimation reads stock_qty, so
the stale value was silently producing wrong RM/Scrap weights (e.g.
275.808 Kg instead of the correct 28.73 Kg for item 100118).
"""

import frappe

BOM_NAME = "BOM-300189-001"


def execute():
	rows = frappe.get_all(
		"BOM Item",
		filters={"parent": BOM_NAME},
		fields=["name", "item_code", "qty", "stock_qty", "conversion_factor"],
	)

	fixed = 0
	for row in rows:
		expected = row.qty * row.conversion_factor
		if row.stock_qty != expected:
			frappe.db.set_value("BOM Item", row.name, "stock_qty", expected, update_modified=False)
			fixed += 1

	frappe.db.commit()

	if fixed:
		frappe.logger().info(
			f"fix_bom_300189_stale_stock_qty: corrected stock_qty on {fixed} row(s) of {BOM_NAME}"
		)
