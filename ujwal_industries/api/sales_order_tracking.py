# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Sales Order Tracking API

End-to-end tracking from Sales Order to Delivery:
SO → Production Plan → Work Order → Job Card → Delivery Note
"""

import frappe
from frappe import _
from frappe.utils import getdate, add_days, nowdate, flt


@frappe.whitelist()
def get_so_items_for_list(sales_orders):
	"""Return item_code and item_name for given Sales Order names (for list view columns)."""
	import json

	if isinstance(sales_orders, str):
		sales_orders = json.loads(sales_orders)
	if not sales_orders:
		return []

	permitted_sales_orders = [
		sales_order
		for sales_order in sales_orders
		if sales_order and frappe.has_permission('Sales Order', 'read', sales_order)
	]
	if not permitted_sales_orders:
		return []

	return frappe.db.sql(
		"""
		SELECT parent, item_code, item_name
		FROM `tabSales Order Item`
		WHERE parenttype = 'Sales Order'
			AND parent IN %(sales_orders)s
		ORDER BY parent, idx
		""",
		{'sales_orders': tuple(permitted_sales_orders)},
		as_dict=True,
	)


@frappe.whitelist()
def get_sales_orders(days="all", limit_page_length=6, limit_page_offset=0,
					  sales_order_filter=None, from_date=None, to_date=None,
					  customer=None, item=None, status=None):
	"""
	Get Sales Orders with complete tracking information (paginated).

	Args:
		days (str): Number of days to look back, or 'all' for all orders
		limit_page_length (int): Number of records to return (default 6)
		limit_page_offset (int): Offset for pagination (default 0)
		sales_order_filter (str): Filter by Sales Order name (partial match)
		from_date (str): Filter by transaction date >= from_date (overrides days)
		to_date (str): Filter by transaction date <= to_date
		customer (str): Filter by customer code or customer name (partial match)
		item (str): Filter by item code or item name in order lines (partial match)
		status (str): Filter by Sales Order status (exact match)

	Returns:
		dict: { "data": [...], "has_more": bool }
	"""
	limit_page_length = int(limit_page_length or 6)
	limit_page_offset = int(limit_page_offset or 0)

	conditions = ["so.docstatus = 1"]
	params = {}

	# Date range: explicit from_date takes priority over the days shorthand
	if from_date:
		conditions.append("so.transaction_date >= %(from_date)s")
		params["from_date"] = from_date
	elif days not in ("all", None, "NaN", "null", ""):
		try:
			params["from_date"] = add_days(nowdate(), -int(days))
			conditions.append("so.transaction_date >= %(from_date)s")
		except (ValueError, TypeError):
			pass

	if to_date:
		conditions.append("so.transaction_date <= %(to_date)s")
		params["to_date"] = to_date

	if sales_order_filter:
		conditions.append("so.name LIKE %(so_filter)s")
		params["so_filter"] = f"%{sales_order_filter}%"

	if customer:
		conditions.append("(so.customer LIKE %(customer)s OR so.customer_name LIKE %(customer)s)")
		params["customer"] = f"%{customer}%"

	if status:
		conditions.append("so.status = %(status)s")
		params["status"] = status

	# Item filter via EXISTS to avoid row duplication
	item_condition = ""
	if item:
		item_condition = """AND EXISTS (
			SELECT 1 FROM `tabSales Order Item` soi
			WHERE soi.parent = so.name
			AND (soi.item_code LIKE %(item)s OR soi.item_name LIKE %(item)s)
		)"""
		params["item"] = f"%{item}%"

	where_clause = " AND ".join(conditions)
	params["limit"] = limit_page_length + 1
	params["offset"] = limit_page_offset

	sales_orders = frappe.db.sql(f"""
		SELECT
			so.name,
			so.customer,
			so.customer_name,
			so.transaction_date,
			so.delivery_date,
			so.status,
			so.grand_total,
			so.currency,
			so.per_delivered,
			so.per_billed
		FROM
			`tabSales Order` so
		WHERE
			{where_clause}
			{item_condition}
		ORDER BY
			so.transaction_date DESC
		LIMIT %(limit)s OFFSET %(offset)s
	""", params, as_dict=1)

	has_more = len(sales_orders) > limit_page_length
	sales_orders = sales_orders[:limit_page_length]

	# Batch-fetch items for all returned SOs (one query, avoids N+1)
	items_by_so = {}
	if sales_orders:
		so_names = [so.name for so in sales_orders]
		all_items = frappe.db.sql("""
			SELECT parent, item_code, item_name, qty, stock_uom
			FROM `tabSales Order Item`
			WHERE parent IN %(so_names)s
			ORDER BY parent, idx
		""", {"so_names": tuple(so_names)}, as_dict=1)
		for item in all_items:
			items_by_so.setdefault(item.parent, []).append(item)

	# Enrich with tracking data (single pass, avoids repeated DB hits)
	for so in sales_orders:
		pp_count = get_production_plan_count(so.name)
		wo_count = get_work_order_count(so.name)
		jc_count = get_job_card_count(so.name)
		dn_count = get_delivery_note_count(so.name)

		# Stage-based progress: 5 fixed stages, each worth 20%
		stages_done = 1  # Stage 1: SO Created (always done)
		if pp_count > 0:
			stages_done += 1  # Stage 2: Production Plan
		if wo_count > 0:
			stages_done += 1  # Stage 3: Work Orders

		# Stage 4: Job Cards (any completed)
		work_orders = frappe.db.get_all(
			'Work Order', {'sales_order': so.name, 'docstatus': ['!=', 2]}, pluck='name'
		)
		jc_completed = 0
		if work_orders:
			jc_completed = frappe.db.count('Job Card', {
				'work_order': ['in', work_orders], 'docstatus': 1, 'status': 'Completed'
			})
			if jc_completed > 0:
				stages_done += 1  # Stage 4: Job Cards progressing

		# Stage 5: Delivery
		if flt(so.get('per_delivered', 0)) >= 100:
			stages_done = 5
		elif flt(so.get('per_delivered', 0)) > 0:
			stages_done = min(stages_done + 1, 5)

		so['stages_done'] = stages_done
		so['total_stages'] = 5
		so['progress'] = round((stages_done / 5) * 100)
		so['job_card_completed'] = jc_completed
		so['production_plan_count'] = pp_count
		so['work_order_count'] = wo_count
		so['job_card_count'] = jc_count
		so['delivery_note_count'] = dn_count
		so['items'] = items_by_so.get(so.name, [])

	return {"data": sales_orders, "has_more": has_more}


def calculate_progress(so):
	"""
	Calculate overall progress percentage for Sales Order.

	Progress stages:
	- Sales Order Created: 10%
	- Production Plan: +20%
	- Work Orders: +30%
	- Job Cards Completed: +20%
	- Delivered: +20%
	"""
	progress = 10  # Base for SO creation

	# Production Plan
	if get_production_plan_count(so['name']) > 0:
		progress += 20

	# Work Orders
	wo_count = get_work_order_count(so['name'])
	if wo_count > 0:
		progress += 30

	# Job Cards (check if any completed via Work Orders)
	work_orders = frappe.db.get_all('Work Order', {
		'sales_order': so['name'],
		'docstatus': ['!=', 2]
	}, pluck='name')

	if work_orders:
		jc_completed = frappe.db.count('Job Card', {
			'work_order': ['in', work_orders],
			'docstatus': 1,
			'status': 'Completed'
		})
		if jc_completed > 0:
			progress += 20

	# Delivery
	if flt(so.get('per_delivered', 0)) >= 100:
		progress = 100
	elif flt(so.get('per_delivered', 0)) > 0:
		progress += 10

	return min(progress, 100)


def get_production_plan_count(sales_order):
	"""Get count of Production Plans linked to Sales Order."""
	return frappe.db.count('Production Plan Item', {
		'sales_order': sales_order,
		'docstatus': ['!=', 2]
	})


def get_work_order_count(sales_order):
	"""Get count of Work Orders linked to Sales Order."""
	return frappe.db.count('Work Order', {
		'sales_order': sales_order,
		'docstatus': ['!=', 2]
	})


def get_job_card_count(sales_order):
	"""Get count of Job Cards linked to Sales Order."""
	# Get via Work Orders
	work_orders = frappe.db.get_all('Work Order', {
		'sales_order': sales_order,
		'docstatus': ['!=', 2]
	}, pluck='name')

	if not work_orders:
		return 0

	return frappe.db.count('Job Card', {
		'work_order': ['in', work_orders],
		'docstatus': ['!=', 2]
	})


def get_delivery_note_count(sales_order):
	"""Get count of Delivery Notes linked to Sales Order."""
	return frappe.db.count('Delivery Note Item', {
		'against_sales_order': sales_order,
		'docstatus': ['!=', 2]
	})


@frappe.whitelist()
def get_sales_order_detail(sales_order):
	"""
	Get detailed tracking information for a specific Sales Order.

	Returns complete timeline with:
	- Production Plans
	- Work Orders
	- Job Cards
	- Delivery Notes
	"""
	so = frappe.get_doc("Sales Order", sales_order)

	# Get Production Plans
	production_plans = get_linked_production_plans(sales_order)

	# Get Work Orders
	work_orders = get_linked_work_orders(sales_order)

	# Get Job Cards (via Work Orders)
	job_cards = get_linked_job_cards(sales_order)

	# Get Delivery Notes
	delivery_notes = get_linked_delivery_notes(sales_order)

	# Get Stock Entries (Material Transfer, Manufacture)
	stock_entries = get_linked_stock_entries(sales_order)

	return {
		"sales_order": {
			"name": so.name,
			"customer": so.customer,
			"customer_name": so.customer_name,
			"transaction_date": so.transaction_date,
			"delivery_date": so.delivery_date,
			"status": so.status,
			"grand_total": so.grand_total
		},
		"production_plans": production_plans,
		"work_orders": work_orders,
		"job_cards": job_cards,
		"stock_entries": stock_entries,
		"delivery_notes": delivery_notes,
		"timeline": build_timeline(so, production_plans, work_orders, job_cards, delivery_notes)
	}


def get_linked_production_plans(sales_order):
	"""Get Production Plans linked to Sales Order."""
	return frappe.db.sql("""
		SELECT DISTINCT
			pp.name,
			pp.posting_date,
			pp.status,
			pp.total_planned_qty,
			pp.total_produced_qty
		FROM
			`tabProduction Plan` pp
		INNER JOIN
			`tabProduction Plan Item` ppi ON ppi.parent = pp.name
		WHERE
			ppi.sales_order = %(sales_order)s
			AND pp.docstatus != 2
		ORDER BY
			pp.posting_date DESC
	""", {"sales_order": sales_order}, as_dict=1)


def get_linked_work_orders(sales_order):
	"""Get Work Orders linked to Sales Order, including item name."""
	return frappe.db.sql("""
		SELECT
			wo.name,
			wo.production_plan,
			wo.production_item,
			item.item_name AS production_item_name,
			wo.qty,
			wo.produced_qty,
			wo.status,
			wo.planned_start_date,
			wo.actual_start_date,
			wo.actual_end_date
		FROM
			`tabWork Order` wo
		LEFT JOIN
			`tabItem` item ON item.name = wo.production_item
		WHERE
			wo.sales_order = %(sales_order)s
			AND wo.docstatus != 2
		ORDER BY
			wo.planned_start_date DESC
	""", {"sales_order": sales_order}, as_dict=1)


def get_linked_job_cards(sales_order):
	"""Get Job Cards linked to Sales Order (via Work Orders)."""
	work_orders = frappe.db.get_all('Work Order', {
		'sales_order': sales_order,
		'docstatus': ['!=', 2]
	}, pluck='name')

	if not work_orders:
		return []

	return frappe.db.sql("""
		SELECT
			name,
			work_order,
			operation,
			status,
			actual_start_date,
			actual_end_date,
			total_time_in_mins
		FROM
			`tabJob Card`
		WHERE
			work_order IN %(work_orders)s
			AND docstatus != 2
		ORDER BY
			actual_start_date DESC
	""", {"work_orders": work_orders}, as_dict=1)


def get_linked_delivery_notes(sales_order):
	"""Get Delivery Notes linked to Sales Order."""
	return frappe.db.sql("""
		SELECT DISTINCT
			dn.name,
			dn.posting_date,
			dn.posting_time,
			dn.status,
			dn.customer
		FROM
			`tabDelivery Note` dn
		INNER JOIN
			`tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE
			dni.against_sales_order = %(sales_order)s
			AND dn.docstatus != 2
		ORDER BY
			dn.posting_date DESC
	""", {"sales_order": sales_order}, as_dict=1)


def get_linked_stock_entries(sales_order):
	"""Get Stock Entries linked to Work Orders of this Sales Order."""
	work_orders = frappe.db.get_all('Work Order', {
		'sales_order': sales_order,
		'docstatus': ['!=', 2]
	}, pluck='name')

	if not work_orders:
		return []

	return frappe.db.sql("""
		SELECT
			name,
			work_order,
			stock_entry_type,
			posting_date,
			docstatus,
			CASE docstatus WHEN 1 THEN 'Submitted' WHEN 0 THEN 'Draft' ELSE 'Cancelled' END as status
		FROM
			`tabStock Entry`
		WHERE
			work_order IN %(work_orders)s
			AND docstatus != 2
		ORDER BY
			posting_date DESC
	""", {"work_orders": work_orders}, as_dict=1)


def build_timeline(so, production_plans, work_orders, job_cards, delivery_notes):
	"""
	Build chronological timeline of all events.
	"""
	from datetime import datetime, date

	def normalize_date(d):
		"""Convert date/datetime to string for consistent sorting."""
		if not d:
			return '1900-01-01'
		if isinstance(d, datetime):
			return d.strftime('%Y-%m-%d')
		elif isinstance(d, date):
			return d.strftime('%Y-%m-%d')
		return str(d)

	timeline = []

	# Sales Order
	timeline.append({
		"type": "Sales Order",
		"name": so.name,
		"date": normalize_date(so.transaction_date),
		"status": so.status,
		"icon": "📝"
	})

	# Production Plans
	for pp in production_plans:
		timeline.append({
			"type": "Production Plan",
			"name": pp.name,
			"date": normalize_date(pp.posting_date),
			"status": pp.status,
			"icon": "📋"
		})

	# Work Orders
	for wo in work_orders:
		timeline.append({
			"type": "Work Order",
			"name": wo.name,
			"date": normalize_date(wo.planned_start_date or wo.actual_start_date),
			"status": wo.status,
			"icon": "⚙️"
		})

	# Job Cards
	for jc in job_cards:
		timeline.append({
			"type": "Job Card",
			"name": jc.name,
			"date": normalize_date(jc.actual_start_date),
			"status": jc.status,
			"icon": "📊"
		})

	# Delivery Notes
	for dn in delivery_notes:
		timeline.append({
			"type": "Delivery Note",
			"name": dn.name,
			"date": normalize_date(dn.posting_date),
			"status": dn.status,
			"icon": "📦"
		})

	# Sort by date (now all strings, consistent comparison)
	timeline.sort(key=lambda x: x.get('date', '1900-01-01'))

	return timeline
