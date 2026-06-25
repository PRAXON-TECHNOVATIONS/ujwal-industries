import frappe
from frappe.utils import add_days, flt, getdate, nowdate


@frappe.whitelist()
def get_subcontract_issued_display_data():
	"""Subcontracted Purchase Orders and the raw material that must be issued for them.

	The Purchase Order is the root (always shown). The raw material to issue, its planned
	and actual dispatch qty, come from the Subcontracting Order raised against the PO
	(linked via Subcontracting Order.purchase_order). Until an SCO exists, those cells
	are left blank; once it's created they populate from its Supplied Items.

	Includes all statuses (incl. Draft) except Completed / Closed / Cancelled. Only POs
	whose Planned Issue Date (transaction_date) is within ..today+3 are shown, so older /
	due-soon orders appear and ones dated further out are hidden.
	"""
	window_end = add_days(nowdate(), 3)

	# Subcontracted PO lines (the "main" rows).
	po_rows = frappe.db.sql(
		"""
		SELECT
			po.name					AS purchase_order,
			po.transaction_date		AS po_posting_date,
			po.supplier				AS supplier_no,
			po.supplier_name		AS supplier_name,
			poi.name				AS po_item_row,
			poi.fg_item				AS fg_item,
			poi.fg_item_qty			AS fg_item_qty
		FROM `tabPurchase Order` po
		INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
		WHERE
			po.docstatus < 2
			AND IFNULL(po.is_subcontracted, 0) = 1
			AND po.status NOT IN ('Completed', 'Closed', 'Cancelled')
			AND DATE(po.transaction_date) <= %(window_end)s
		ORDER BY po.transaction_date ASC, po.name ASC
		""",
		{"window_end": window_end},
		as_dict=True,
	)

	if not po_rows:
		return []

	po_names = list({r.purchase_order for r in po_rows})
	supplied_by_po = _get_supplied_items_by_po(po_names)

	# Stock for every RM we will display.
	rm_codes = {
		s["rm_item_code"]
		for items in supplied_by_po.values()
		for s in items
		if s.get("rm_item_code")
	}
	stock_by_item = _get_stock_by_item(list(rm_codes))
	today = getdate(nowdate())

	data = []
	seen_blank_po = set()
	for po in po_rows:
		delay_days = None
		if po.po_posting_date:
			delay_days = (today - getdate(po.po_posting_date)).days
		common = {
			"purchase_order": po.purchase_order,
			"planned_issue_date": po.po_posting_date,
			"delay_days": delay_days,
			"supplier_no": po.supplier_no,
			"supplier_name": po.supplier_name,
		}

		supplied = supplied_by_po.get(po.purchase_order, [])

		if not supplied:
			# No Subcontracting Order yet — show a single PO row with RM columns blank
			# (the PO can have many "Job Work" lines; one blank row per PO is enough
			# until an SCO is made and the actual RM-to-issue is known).
			if po.purchase_order in seen_blank_po:
				continue
			seen_blank_po.add(po.purchase_order)
			data.append(
				{
					**common,
					"issued_item_no": None,
					"issued_item_name": None,
					"stock_total_qty": None,
					"warehouse_breakup": None,
					"planned_dispatch_qty": None,
					"actual_dispatch_qty": None,
					"balance_qty": None,
				}
			)
			continue

		for s in supplied:
			planned = flt(s["required_qty"])
			actual = flt(s["total_supplied_qty"])
			stock = stock_by_item.get(s["rm_item_code"], {})
			data.append(
				{
					**common,
					"issued_item_no": s["rm_item_code"],
					"issued_item_name": s.get("rm_item_name"),
					"stock_total_qty": flt(stock.get("total")),
					"warehouse_breakup": stock.get("breakup", ""),
					"planned_dispatch_qty": planned,
					"actual_dispatch_qty": actual,
					"balance_qty": max(planned - actual, 0),
				}
			)

	return data


def _get_supplied_items_by_po(po_names):
	"""RM supplied-item rows from Subcontracting Orders, grouped by the linked PO.

	One Subcontracting Order links to its source PO via `purchase_order`. We roll up its
	Supplied Items (the RM to issue) per PO + RM item.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			sco.purchase_order			AS purchase_order,
			sci.rm_item_code			AS rm_item_code,
			rm.item_name				AS rm_item_name,
			SUM(sci.required_qty)		AS required_qty,
			SUM(sci.total_supplied_qty)	AS total_supplied_qty
		FROM `tabSubcontracting Order` sco
		INNER JOIN `tabSubcontracting Order Supplied Item` sci ON sci.parent = sco.name
		LEFT JOIN `tabItem` rm ON rm.name = sci.rm_item_code
		WHERE
			sco.docstatus < 2
			AND sco.status NOT IN ('Completed', 'Cancelled', 'Closed')
			AND sco.purchase_order IN %(po_names)s
		GROUP BY sco.purchase_order, sci.rm_item_code
		""",
		{"po_names": po_names},
		as_dict=True,
	)

	by_po = {}
	for r in rows:
		by_po.setdefault(r.purchase_order, []).append(r)
	return by_po


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
		wh = (b.warehouse or "").split(" - ")[0]
		entry["parts"].append(f"{wh}: {flt(b.actual_qty):g}")

	return {
		code: {"total": v["total"], "breakup": ", ".join(v["parts"])}
		for code, v in by_item.items()
	}
