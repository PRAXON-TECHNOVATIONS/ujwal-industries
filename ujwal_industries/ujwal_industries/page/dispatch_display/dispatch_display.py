import json

import frappe
from frappe.utils import add_days, flt, getdate, nowdate


@frappe.whitelist()
def get_dispatch_display_data():
	"""Dispatch buckets derived from Bulk Pre Production Plan FG batch schedules.

	In the BPP FG batch grid the user ticks the "Dispatch" checkbox on a batch to close a
	dispatch bucket: it covers every batch since the previous tick, its qty is their sum,
	and its delivery date is the ticked batch's end date. Trailing batches after the last
	tick auto-form a final bucket. If no batch in an FG is ticked, the whole FG is one
	bucket delivered on the Sales Order's delivery date.

	Only buckets whose delivery date is within ..today+3 are shown (due-soon / overdue);
	ones planned further out are hidden.
	"""
	window_end = getdate(add_days(nowdate(), 3))
	today = getdate(nowdate())

	# Newest BPP first so that, when several plans cover the same Sales Order + FG item,
	# only the latest one's dispatch buckets are used (avoids double counting).
	plans = frappe.db.sql(
		"""
		SELECT name, custom_batch_schedule
		FROM `tabBulk Pre Production Plan`
		WHERE custom_batch_schedule IS NOT NULL AND custom_batch_schedule != ''
		ORDER BY modified DESC
		""",
		as_dict=True,
	)

	buckets = []
	seen_so_fg = set()
	for plan in plans:
		try:
			schedule = json.loads(plan.custom_batch_schedule)
		except Exception:
			continue
		if not isinstance(schedule, dict):
			continue

		for so_slice in schedule.values():
			if not isinstance(so_slice, dict):
				continue
			so_delivery = so_slice.get("delivery_date")
			for fg in so_slice.get("fg") or []:
				key = (fg.get("sales_order"), fg.get("item_code"))
				if key in seen_so_fg:
					continue  # an newer BPP already covered this SO + FG
				seen_so_fg.add(key)
				buckets.extend(_buckets_for_fg(plan.name, fg, so_delivery))

	if not buckets:
		return []

	# Actual dispatched qty per (Sales Order, FG item) from submitted Delivery Notes,
	# allocated to buckets in delivery-date order (earliest bucket filled first).
	delivered = _get_delivered_qty(buckets)
	_allocate_delivered_to_buckets(buckets, delivered)

	# FG stock for every item we will show.
	item_codes = list({b["item_no"] for b in buckets if b["item_no"]})
	stock_by_item = _get_stock_by_item(item_codes)

	data = []
	for b in buckets:
		delivery = b["planned_delivery_date"]
		if not delivery or getdate(delivery) > window_end:
			continue

		delay_days = (today - getdate(delivery)).days
		stock = stock_by_item.get(b["item_no"], {})
		planned = flt(b["planned_dispatch_qty"])
		actual = flt(b["actual_dispatch_qty"])

		data.append(
			{
				"sales_order": b["sales_order"],
				"item_no": b["item_no"],
				"item_name": b["item_name"],
				"fg_stock_total_qty": flt(stock.get("total")),
				"warehouse_breakup": stock.get("breakup", ""),
				"planned_dispatch_qty": planned,
				"actual_dispatch_qty": actual,
				"balance_qty": max(planned - actual, 0),
				"planned_delivery_date": delivery,
				"delay_days": delay_days,
				"bulk_pp": b["bulk_pp"],
				"dispatch_label": b["dispatch_label"],
			}
		)

	# Soonest delivery first.
	data.sort(key=lambda r: getdate(r["planned_delivery_date"]))
	return data


def _buckets_for_fg(plan_name, fg, so_delivery):
	"""Split an FG's batches into dispatch buckets based on the ticked batches."""
	batches = fg.get("batches") or []
	item_no = fg.get("item_code")
	item_name = fg.get("item_name")
	sales_order = fg.get("sales_order")

	# No batches at all -> nothing to dispatch.
	if not batches:
		return []

	ticked_idx = [i for i, b in enumerate(batches) if b.get("dispatch")]

	# No tick -> one bucket for the whole FG, on the SO delivery date.
	if not ticked_idx:
		return [
			{
				"bulk_pp": plan_name,
				"sales_order": sales_order,
				"item_no": item_no,
				"item_name": item_name,
				"planned_dispatch_qty": sum(flt(b.get("qty")) for b in batches),
				"actual_dispatch_qty": 0,
				"planned_delivery_date": so_delivery,
				"dispatch_label": "Full order",
			}
		]

	buckets = []
	start = 0
	for n, end_i in enumerate(ticked_idx, start=1):
		group = batches[start : end_i + 1]
		buckets.append(
			{
				"bulk_pp": plan_name,
				"sales_order": sales_order,
				"item_no": item_no,
				"item_name": item_name,
				"planned_dispatch_qty": sum(flt(b.get("qty")) for b in group),
				"actual_dispatch_qty": 0,
				"planned_delivery_date": batches[end_i].get("end_date"),
				"dispatch_label": f"Dispatch {n} (batches {start + 1}-{end_i + 1})",
			}
		)
		start = end_i + 1

	# Trailing batches after the last tick -> auto final bucket.
	if start < len(batches):
		group = batches[start:]
		buckets.append(
			{
				"bulk_pp": plan_name,
				"sales_order": sales_order,
				"item_no": item_no,
				"item_name": item_name,
				"planned_dispatch_qty": sum(flt(b.get("qty")) for b in group),
				"actual_dispatch_qty": 0,
				"planned_delivery_date": batches[-1].get("end_date"),
				"dispatch_label": f"Dispatch {len(ticked_idx) + 1} (batches {start + 1}-{len(batches)})",
			}
		)

	return buckets


def _get_delivered_qty(buckets):
	"""Delivered qty per (Sales Order, FG item) from submitted Delivery Notes."""
	pairs = {(b["sales_order"], b["item_no"]) for b in buckets if b["sales_order"] and b["item_no"]}
	if not pairs:
		return {}

	sos = list({p[0] for p in pairs})
	items = list({p[1] for p in pairs})

	rows = frappe.db.sql(
		"""
		SELECT dni.against_sales_order AS sales_order, dni.item_code AS item_code,
			SUM(dni.qty) AS qty
		FROM `tabDelivery Note Item` dni
		INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE
			dn.docstatus = 1
			AND dni.against_sales_order IN %(sos)s
			AND dni.item_code IN %(items)s
		GROUP BY dni.against_sales_order, dni.item_code
		""",
		{"sos": sos, "items": items},
		as_dict=True,
	)
	return {(r.sales_order, r.item_code): flt(r.qty) for r in rows}


def _allocate_delivered_to_buckets(buckets, delivered):
	"""Spread each (SO, FG)'s delivered qty across its buckets, earliest delivery first."""
	from collections import defaultdict

	groups = defaultdict(list)
	for b in buckets:
		groups[(b["sales_order"], b["item_no"])].append(b)

	for key, group in groups.items():
		remaining = flt(delivered.get(key, 0))
		# Earliest delivery date first; undated buckets last.
		group.sort(key=lambda b: (b["planned_delivery_date"] is None, b["planned_delivery_date"] or ""))
		for b in group:
			if remaining <= 0:
				break
			take = min(flt(b["planned_dispatch_qty"]), remaining)
			b["actual_dispatch_qty"] = take
			remaining -= take


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
