import frappe
from frappe.utils import flt, getdate, nowdate


@frappe.whitelist()
def get_purchase_order_display_data():
	"""One row per Purchase Order Item for active (non subcontracted) Purchase Orders.

	Excludes Cancelled / Completed / Closed POs and subcontracted POs. Draft and all
	in-progress POs are included so the buyer/store can see what still needs work.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			po.name				AS purchase_order,
			po.transaction_date	AS po_start_date,
			po.supplier			AS supplier_no,
			po.supplier_name	AS supplier_name,
			poi.name			AS po_item_row,
			poi.item_code		AS po_item_no,
			poi.item_name		AS po_item_name,
			poi.qty				AS planned_received_qty,
			poi.received_qty	AS actual_received_qty,
			poi.schedule_date	AS planned_received_date,
			poi.material_request,
			mr.transaction_date	AS pr_start_date
		FROM `tabPurchase Order` po
		INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
		LEFT JOIN `tabMaterial Request` mr ON mr.name = poi.material_request
		WHERE
			po.docstatus < 2
			AND IFNULL(po.is_subcontracted, 0) = 0
			AND po.status NOT IN ('Completed', 'Closed', 'Cancelled')
		ORDER BY poi.schedule_date ASC, po.name ASC
		""",
		as_dict=True,
	)

	if not rows:
		return []

	item_codes = list({r.po_item_no for r in rows if r.po_item_no})
	stock_by_item = _get_stock_by_item(item_codes)
	today = getdate(nowdate())

	data = []
	for r in rows:
		planned = flt(r.planned_received_qty)
		actual = flt(r.actual_received_qty)
		balance_qty = max(planned - actual, 0)

		# Delay (PR Start - PO Start): days between Material Request and PO posting dates.
		pr_to_po_days = None
		if r.pr_start_date and r.po_start_date:
			pr_to_po_days = (getdate(r.po_start_date) - getdate(r.pr_start_date)).days

		# Delay (Planned Received - Current): >0 means receipt is overdue.
		recv_delay_days = None
		if r.planned_received_date:
			recv_delay_days = (today - getdate(r.planned_received_date)).days

		stock = stock_by_item.get(r.po_item_no, {})

		data.append(
			{
				"purchase_order": r.purchase_order,
				"po_item_no": r.po_item_no,
				"po_item_name": r.po_item_name,
				"po_start_date": r.po_start_date,
				"planned_received_qty": planned,
				"actual_received_qty": actual,
				"balance_qty": balance_qty,
				"planned_received_date": r.planned_received_date,
				"pr_to_po_days": pr_to_po_days,
				"recv_delay_days": recv_delay_days,
				"supplier_no": r.supplier_no,
				"supplier_name": r.supplier_name,
				"stock_total_qty": flt(stock.get("total")),
				"warehouse_breakup": stock.get("breakup", ""),
			}
		)

	return data


def _get_stock_by_item(item_codes):
	"""Total and per-warehouse on-hand qty for each item, from Bin."""
	if not item_codes:
		return {}

	bins = frappe.db.sql(
		"""
		SELECT item_code, warehouse, actual_qty
		FROM `tabBin`
		WHERE item_code IN %(items)s AND actual_qty != 0
		ORDER BY actual_qty DESC
		""",
		{"items": item_codes},
		as_dict=True,
	)

	by_item = {}
	for b in bins:
		entry = by_item.setdefault(b.item_code, {"total": 0.0, "parts": []})
		entry["total"] += flt(b.actual_qty)
		# Short warehouse label (drop the " - ABBR" company suffix for readability).
		wh = (b.warehouse or "").split(" - ")[0]
		entry["parts"].append(f"{wh}: {flt(b.actual_qty):g}")

	return {
		code: {"total": v["total"], "breakup": ", ".join(v["parts"])}
		for code, v in by_item.items()
	}
