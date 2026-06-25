import frappe
from frappe.utils import add_days, flt, getdate, nowdate


@frappe.whitelist()
def get_subcontract_received_display_data():
	"""Finished goods to be received back from the subcontractor, per subcontracted PO line.

	FG-focused (the opposite of Subcontract Issued, which is RM-focused): shows the
	finished item the subcontractor produces (poi.fg_item), how much was ordered vs
	actually received (poi.received_qty), and what's still pending.

	Includes all statuses (incl. Draft) except Completed / Closed / Cancelled. Only lines
	whose planned received date (schedule_date) is within ..today+3 are shown, so older /
	due-soon receipts appear and ones dated further out are hidden.
	"""
	window_end = add_days(nowdate(), 3)

	# Subcontracted POs have many "Job Work" lines that share the same FG item; roll them
	# up to one row per (PO, FG item) with summed planned qty and the earliest schedule
	# date, so the buyer sees "this PO owes N of FG X".
	rows = frappe.db.sql(
		"""
		SELECT
			po.name				AS purchase_order,
			po.transaction_date	AS po_start_date,
			po.supplier			AS supplier_no,
			po.supplier_name	AS supplier_name,
			poi.fg_item			AS po_item_no,
			fg.item_name		AS po_item_name,
			SUM(poi.fg_item_qty)	AS planned_received_qty,
			MIN(poi.schedule_date)	AS planned_received_date
		FROM `tabPurchase Order` po
		INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
		LEFT JOIN `tabItem` fg ON fg.name = poi.fg_item
		WHERE
			po.docstatus < 2
			AND IFNULL(po.is_subcontracted, 0) = 1
			AND po.status NOT IN ('Completed', 'Closed', 'Cancelled')
			AND poi.fg_item IS NOT NULL
			AND DATE(poi.schedule_date) <= %(window_end)s
		GROUP BY po.name, poi.fg_item
		ORDER BY MIN(poi.schedule_date) ASC, po.name ASC
		""",
		{"window_end": window_end},
		as_dict=True,
	)

	if not rows:
		return []

	# Actual FG received comes from Subcontracting Receipts (the authoritative source).
	# A PR only carries the "Job Work" service line, so relying on PO Item.received_qty
	# misses cases where only a Subcontracting Receipt was made.
	po_names = list({r.purchase_order for r in rows})
	received_by_po_item = _get_received_qty_by_po_item(po_names)

	today = getdate(nowdate())

	data = []
	for r in rows:
		planned = flt(r.planned_received_qty)
		actual = flt(received_by_po_item.get((r.purchase_order, r.po_item_no), 0))
		balance_qty = max(planned - actual, 0)

		# Delay = today - PO start date (Planned Start Date).
		delay_days = None
		if r.po_start_date:
			delay_days = (today - getdate(r.po_start_date)).days

		data.append(
			{
				"purchase_order": r.purchase_order,
				"po_item_no": r.po_item_no,
				"po_item_name": r.po_item_name,
				"planned_received_qty": planned,
				"actual_received_qty": actual,
				"balance_qty": balance_qty,
				"planned_received_date": r.planned_received_date,
				"delay_days": delay_days,
				"supplier_no": r.supplier_no,
				"supplier_name": r.supplier_name,
			}
		)

	return data


def _get_received_qty_by_po_item(po_names):
	"""FG qty actually received, summed per (Purchase Order, FG item code).

	Source is Subcontracting Receipt Items (submitted, non-return), which is where the
	finished good is recorded — the linked Purchase Receipt only holds the Job Work
	service line.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			sri.purchase_order		AS purchase_order,
			sri.item_code			AS item_code,
			SUM(sri.received_qty)	AS received_qty
		FROM `tabSubcontracting Receipt Item` sri
		INNER JOIN `tabSubcontracting Receipt` scr ON scr.name = sri.parent
		WHERE
			scr.docstatus = 1
			AND IFNULL(scr.is_return, 0) = 0
			AND sri.purchase_order IN %(po_names)s
		GROUP BY sri.purchase_order, sri.item_code
		""",
		{"po_names": po_names},
		as_dict=True,
	)
	return {(r.purchase_order, r.item_code): flt(r.received_qty) for r in rows}
