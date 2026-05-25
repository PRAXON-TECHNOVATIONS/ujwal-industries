# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Owner Dashboard API
Three views: Manufacturing Command Center | Inventory & Supply Chain | Financial & Delivery
"""

import math
from datetime import timedelta

import frappe
from frappe.utils import nowdate, add_days, flt, getdate, today


# ─────────────────────────────────────────────
#  TOP-LEVEL ENTRY POINTS
# ─────────────────────────────────────────────

@frappe.whitelist()
def get_manufacturing_data():
	"""Dashboard 1: Manufacturing Command Center."""
	return {
		"kpis": get_manufacturing_kpis(),
		"bottlenecks": get_work_order_bottlenecks(),
		"workstation_load": get_workstation_load(),
		"production_vs_plan": get_production_vs_plan(),
		"overdue_job_cards": get_overdue_job_cards(),
	}


@frappe.whitelist()
def get_inventory_data():
	"""Dashboard 2: Inventory & Supply Chain Risk."""
	return {
		"kpis": get_inventory_kpis(),
		"rm_shortage": get_rm_shortage(),
		"subcontract_exposure": get_subcontract_exposure(),
		"inventory_ageing": get_inventory_ageing(),
	}


@frappe.whitelist()
def get_financial_data():
	"""Dashboard 3: Financial & Delivery Risk."""
	return {
		"kpis": get_financial_kpis(),
		"delivery_risk": get_delivery_risk_orders(),
		"delayed_dispatches": get_delayed_dispatches(),
		"financial_leakage": get_financial_leakage(),
	}


# ─────────────────────────────────────────────
#  DASHBOARD 1 — MANUFACTURING
# ─────────────────────────────────────────────

def get_manufacturing_kpis():
	active_wo = frappe.db.count("Work Order", {
		"status": ["in", ["In Process", "Not Started"]],
		"docstatus": 1
	})

	# WOs where produced_qty < qty and planned_end_date overdue
	overdue_wo = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabWork Order`
		WHERE docstatus = 1
		  AND status NOT IN ('Completed', 'Stopped')
		  AND planned_end_date < %(today)s
	""", {"today": nowdate()})[0][0] or 0

	# Job cards pending (open/working, past expected date)
	overdue_jc = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabJob Card`
		WHERE docstatus = 1
		  AND status NOT IN ('Completed')
		  AND expected_end_date < %(today)s
	""", {"today": nowdate()})[0][0] or 0

	# Today's production achievement: produced_qty / qty for WOs in process
	prod_rows = frappe.db.sql("""
		SELECT SUM(qty) as planned, SUM(produced_qty) as actual
		FROM `tabWork Order`
		WHERE docstatus = 1 AND status = 'In Process'
	""", as_dict=1)
	planned = flt(prod_rows[0].planned) if prod_rows else 0
	actual = flt(prod_rows[0].actual) if prod_rows else 0
	production_achievement = round((actual / planned) * 100) if planned > 0 else 0

	# Total WOs in system (for blocked calculation)
	blocked_wo = frappe.db.count("Work Order", {
		"status": "Stopped",
		"docstatus": 1
	})

	# Pending stock entries (WOs completed but manufacture entry pending)
	pending_mfg_entry = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabWork Order`
		WHERE docstatus = 1
		  AND status = 'In Process'
		  AND produced_qty > 0
		  AND produced_qty < qty
	""")[0][0] or 0

	return {
		"active_work_orders": active_wo,
		"blocked_work_orders": blocked_wo,
		"overdue_work_orders": overdue_wo,
		"production_achievement": production_achievement,
		"overdue_job_cards": overdue_jc,
		"pending_mfg_entries": pending_mfg_entry,
	}


def get_work_order_bottlenecks():
	"""Work Orders that are overdue or stopped."""
	rows = frappe.db.sql("""
		SELECT
			wo.name,
			wo.production_item,
			item.item_name,
			wo.status,
			wo.qty,
			wo.produced_qty,
			wo.planned_end_date,
			wo.sales_order
		FROM `tabWork Order` wo
		LEFT JOIN `tabItem` item ON item.name = wo.production_item
		WHERE wo.docstatus = 1
		  AND wo.status IN ('Stopped', 'In Process')
		  AND (wo.planned_end_date < %(today)s OR wo.status = 'Stopped')
		ORDER BY wo.planned_end_date ASC
		LIMIT 10
	""", {"today": nowdate()}, as_dict=1)

	result = []
	for r in rows:
		days_overdue = (getdate(nowdate()) - getdate(r.planned_end_date)).days if r.planned_end_date else 0
		pct = round((flt(r.produced_qty) / flt(r.qty)) * 100) if r.qty else 0
		result.append({
			"name": r.name,
			"item": r.production_item,
			"item_name": r.item_name or r.production_item,
			"status": r.status,
			"pct_complete": pct,
			"days_overdue": days_overdue,
			"sales_order": r.sales_order,
		})
	return result


def get_workstation_load():
	"""Active job cards grouped by workstation with completion %."""
	rows = frappe.db.sql("""
		SELECT
			jc.workstation,
			COUNT(*) as total_cards,
			SUM(CASE WHEN jc.status = 'Completed' THEN 1 ELSE 0 END) as completed,
			SUM(CASE WHEN jc.status IN ('Open','Working') THEN 1 ELSE 0 END) as in_progress,
			SUM(CASE WHEN jc.status = 'On Hold' THEN 1 ELSE 0 END) as on_hold
		FROM `tabJob Card` jc
		WHERE jc.docstatus = 1
		  AND jc.workstation IS NOT NULL AND jc.workstation != ''
		GROUP BY jc.workstation
		ORDER BY in_progress DESC
		LIMIT 8
	""", as_dict=1)

	result = []
	for r in rows:
		util = round((r.in_progress / r.total_cards) * 100) if r.total_cards else 0
		result.append({
			"workstation": r.workstation,
			"total": r.total_cards,
			"completed": r.completed,
			"in_progress": r.in_progress,
			"on_hold": r.on_hold,
			"utilization": util,
		})
	return result


def get_production_vs_plan():
	"""Recent Production Plans: planned qty vs produced qty."""
	rows = frappe.db.sql("""
		SELECT
			name,
			status,
			total_planned_qty,
			total_produced_qty,
			posting_date
		FROM `tabProduction Plan`
		WHERE docstatus = 1
		ORDER BY posting_date DESC
		LIMIT 8
	""", as_dict=1)

	result = []
	for r in rows:
		pct = round((flt(r.total_produced_qty) / flt(r.total_planned_qty)) * 100) if r.total_planned_qty else 0
		result.append({
			"name": r.name,
			"status": r.status,
			"planned": flt(r.total_planned_qty),
			"actual": flt(r.total_produced_qty),
			"pct": pct,
			"posting_date": str(r.posting_date) if r.posting_date else "",
		})
	return result


def get_overdue_job_cards():
	"""Job Cards that are overdue (past expected end date)."""
	rows = frappe.db.sql("""
		SELECT
			jc.name,
			jc.work_order,
			jc.operation,
			jc.workstation,
			jc.status,
			jc.expected_end_date,
			wo.production_item,
			wo.sales_order
		FROM `tabJob Card` jc
		LEFT JOIN `tabWork Order` wo ON wo.name = jc.work_order
		WHERE jc.docstatus = 1
		  AND jc.status NOT IN ('Completed')
		  AND jc.expected_end_date < %(today)s
		ORDER BY jc.expected_end_date ASC
		LIMIT 10
	""", {"today": nowdate()}, as_dict=1)

	result = []
	for r in rows:
		days_overdue = (getdate(nowdate()) - getdate(r.expected_end_date)).days if r.expected_end_date else 0
		result.append({
			"name": r.name,
			"work_order": r.work_order,
			"operation": r.operation,
			"workstation": r.workstation,
			"status": r.status,
			"days_overdue": days_overdue,
			"item": r.production_item,
			"sales_order": r.sales_order,
		})
	return result


# ─────────────────────────────────────────────
#  DASHBOARD 2 — INVENTORY
# ─────────────────────────────────────────────

def get_inventory_kpis():
	# Total inventory value from latest stock ledger
	inv_value_row = frappe.db.sql("""
		SELECT SUM(stock_value) as total_value
		FROM `tabBin`
		WHERE actual_qty > 0
	""", as_dict=1)
	total_inventory_value = flt(inv_value_row[0].total_value) if inv_value_row else 0

	# Items below reorder level
	rm_shortage = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabBin` b
		INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.actual_qty < b.reserved_qty
		  AND b.actual_qty >= 0
	""")[0][0] or 0

	# Items with no movement in 90 days (non-moving stock value)
	non_moving_value = frappe.db.sql("""
		SELECT SUM(b.stock_value) as val
		FROM `tabBin` b
		WHERE b.actual_qty > 0
		  AND (b.last_sle_id IS NULL OR b.modified < %(cutoff)s)
	""", {"cutoff": add_days(nowdate(), -90)}, as_dict=1)
	non_moving = flt(non_moving_value[0].val) if non_moving_value else 0

	# Subcontract: stock sent to subcontractors
	subcontract_value = frappe.db.sql("""
		SELECT SUM(b.stock_value) as val
		FROM `tabBin` b
		INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
		WHERE w.warehouse_type = 'Transit'
		  AND b.actual_qty > 0
	""", as_dict=1)
	subcontract = flt(subcontract_value[0].val) if subcontract_value else 0

	# Rejected material: items in rejected/QC rejected warehouses
	rejected_value = frappe.db.sql("""
		SELECT SUM(b.stock_value) as val
		FROM `tabBin` b
		INNER JOIN `tabWarehouse` w ON w.name = b.warehouse
		WHERE (LOWER(w.warehouse_name) LIKE '%reject%'
		    OR LOWER(w.warehouse_name) LIKE '%scrap%'
		    OR LOWER(w.warehouse_name) LIKE '%qc%')
		  AND b.actual_qty > 0
	""", as_dict=1)
	rejected = flt(rejected_value[0].val) if rejected_value else 0

	# Open Purchase Orders value
	open_po_value = frappe.db.sql("""
		SELECT SUM(grand_total) as val
		FROM `tabPurchase Order`
		WHERE docstatus = 1 AND status NOT IN ('Completed', 'Cancelled', 'Closed')
	""", as_dict=1)
	open_po = flt(open_po_value[0].val) if open_po_value else 0

	return {
		"total_inventory_value": total_inventory_value,
		"rm_shortage_items": rm_shortage,
		"non_moving_value": non_moving,
		"subcontract_value": subcontract,
		"rejected_value": rejected,
		"open_po_value": open_po,
	}


def get_rm_shortage():
	"""Items where actual qty < reserved qty (shortage risk)."""
	rows = frappe.db.sql("""
		SELECT
			b.item_code,
			i.item_name,
			b.warehouse,
			b.actual_qty,
			b.reserved_qty,
			b.stock_value,
			i.stock_uom
		FROM `tabBin` b
		INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.actual_qty < b.reserved_qty
		  AND b.reserved_qty > 0
		ORDER BY (b.reserved_qty - b.actual_qty) DESC
		LIMIT 10
	""", as_dict=1)

	result = []
	for r in rows:
		result.append({
			"item_code": r.item_code,
			"item_name": r.item_name or r.item_code,
			"warehouse": r.warehouse,
			"available": flt(r.actual_qty),
			"required": flt(r.reserved_qty),
			"shortfall": flt(r.reserved_qty) - flt(r.actual_qty),
			"uom": r.stock_uom,
		})
	return result


def get_subcontract_exposure():
	"""Open Subcontracting Orders with pending receipts."""
	rows = frappe.db.sql("""
		SELECT
			po.name,
			po.supplier,
			po.transaction_date,
			po.grand_total,
			po.status
		FROM `tabPurchase Order` po
		WHERE po.docstatus = 1
		  AND po.is_subcontracted = 1
		  AND po.status NOT IN ('Completed', 'Cancelled', 'Closed')
		ORDER BY po.transaction_date DESC
		LIMIT 8
	""", as_dict=1)

	result = []
	for r in rows:
		days_open = (getdate(nowdate()) - getdate(r.transaction_date)).days if r.transaction_date else 0
		result.append({
			"name": r.name,
			"supplier": r.supplier,
			"value": flt(r.grand_total),
			"days_open": days_open,
			"status": r.status,
		})
	return result


def get_inventory_ageing():
	"""Stock value grouped by age buckets based on last movement date."""
	buckets = [
		{"label": "0–30 Days", "days": 30, "risk": "Normal"},
		{"label": "31–60 Days", "days": 60, "risk": "Watch"},
		{"label": "61–90 Days", "days": 90, "risk": "High"},
		{"label": ">90 Days", "days": 999, "risk": "Cash Blocked"},
	]

	result = []
	prev_cutoff = nowdate()

	for i, bucket in enumerate(buckets):
		cutoff = add_days(nowdate(), -bucket["days"]) if bucket["days"] < 999 else "2000-01-01"
		prev = add_days(nowdate(), -(buckets[i-1]["days"]) if i > 0 else 0)

		if i == 0:
			val_row = frappe.db.sql("""
				SELECT SUM(b.stock_value) as val FROM `tabBin` b
				WHERE b.actual_qty > 0 AND b.modified >= %(cutoff)s
			""", {"cutoff": add_days(nowdate(), -30)}, as_dict=1)
		elif i == len(buckets) - 1:
			val_row = frappe.db.sql("""
				SELECT SUM(b.stock_value) as val FROM `tabBin` b
				WHERE b.actual_qty > 0 AND b.modified < %(cutoff)s
			""", {"cutoff": add_days(nowdate(), -90)}, as_dict=1)
		else:
			from_date = add_days(nowdate(), -bucket["days"])
			to_date = add_days(nowdate(), -(buckets[i-1]["days"]))
			val_row = frappe.db.sql("""
				SELECT SUM(b.stock_value) as val FROM `tabBin` b
				WHERE b.actual_qty > 0 AND b.modified >= %(from_d)s AND b.modified < %(to_d)s
			""", {"from_d": from_date, "to_d": to_date}, as_dict=1)

		result.append({
			"label": bucket["label"],
			"value": flt(val_row[0].val) if val_row else 0,
			"risk": bucket["risk"],
		})
	return result


# ─────────────────────────────────────────────
#  DASHBOARD 3 — FINANCIAL & DELIVERY
# ─────────────────────────────────────────────

def get_financial_kpis():
	# Orders at delivery risk: SO delivery date within next 7 days and not fully delivered
	delivery_risk_count = frappe.db.sql("""
		SELECT COUNT(*) FROM `tabSales Order`
		WHERE docstatus = 1
		  AND status NOT IN ('Completed', 'Cancelled', 'Closed')
		  AND delivery_date BETWEEN %(today)s AND %(in7)s
		  AND per_delivered < 100
	""", {"today": nowdate(), "in7": add_days(nowdate(), 7)})[0][0] or 0

	delivery_risk_value = frappe.db.sql("""
		SELECT SUM(grand_total) FROM `tabSales Order`
		WHERE docstatus = 1
		  AND status NOT IN ('Completed', 'Cancelled', 'Closed')
		  AND delivery_date BETWEEN %(today)s AND %(in7)s
		  AND per_delivered < 100
	""", {"today": nowdate(), "in7": add_days(nowdate(), 7)})[0][0] or 0

	# Overdue deliveries (delivery date past, not complete)
	overdue_delivery_value = frappe.db.sql("""
		SELECT SUM(grand_total) FROM `tabSales Order`
		WHERE docstatus = 1
		  AND status NOT IN ('Completed', 'Cancelled', 'Closed')
		  AND delivery_date < %(today)s
		  AND per_delivered < 100
	""", {"today": nowdate()})[0][0] or 0

	# Delivered Not Invoiced: Delivery Notes submitted but not billed
	delivered_not_invoiced = frappe.db.sql("""
		SELECT SUM(grand_total) FROM `tabDelivery Note`
		WHERE docstatus = 1
		  AND status NOT IN ('Completed', 'Cancelled', 'Closed')
		  AND per_billed < 100
	""")[0][0] or 0

	# Customer Outstanding (AR)
	customer_outstanding = frappe.db.sql("""
		SELECT SUM(outstanding_amount) FROM `tabSales Invoice`
		WHERE docstatus = 1 AND outstanding_amount > 0
	""")[0][0] or 0

	# Supplier Outstanding (AP)
	supplier_outstanding = frappe.db.sql("""
		SELECT SUM(outstanding_amount) FROM `tabPurchase Invoice`
		WHERE docstatus = 1 AND outstanding_amount > 0
	""")[0][0] or 0

	return {
		"delivery_risk_count": delivery_risk_count,
		"delivery_risk_value": flt(delivery_risk_value),
		"overdue_delivery_value": flt(overdue_delivery_value),
		"delivered_not_invoiced": flt(delivered_not_invoiced),
		"customer_outstanding": flt(customer_outstanding),
		"supplier_outstanding": flt(supplier_outstanding),
	}


def get_delivery_risk_orders():
	"""SOs at delivery risk: due in next 14 days and not fully delivered."""
	rows = frappe.db.sql("""
		SELECT
			name,
			customer,
			customer_name,
			delivery_date,
			grand_total,
			per_delivered,
			status
		FROM `tabSales Order`
		WHERE docstatus = 1
		  AND status NOT IN ('Completed', 'Cancelled', 'Closed')
		  AND delivery_date <= %(in14)s
		  AND per_delivered < 100
		ORDER BY delivery_date ASC
		LIMIT 10
	""", {"in14": add_days(nowdate(), 14)}, as_dict=1)

	result = []
	for r in rows:
		days_left = (getdate(r.delivery_date) - getdate(nowdate())).days if r.delivery_date else 999
		result.append({
			"name": r.name,
			"customer": r.customer,
			"customer_name": r.customer_name or r.customer,
			"delivery_date": str(r.delivery_date) if r.delivery_date else "",
			"days_left": days_left,
			"value": flt(r.grand_total),
			"per_delivered": flt(r.per_delivered),
			"status": r.status,
		})
	return result


def get_delayed_dispatches():
	"""Delivery Notes that are submitted but not closed (dispatch pending)."""
	rows = frappe.db.sql("""
		SELECT
			dn.name,
			dn.customer,
			dn.customer_name,
			dn.posting_date,
			dn.grand_total,
			dn.status,
			dn.per_billed
		FROM `tabDelivery Note` dn
		WHERE dn.docstatus = 1
		  AND dn.status NOT IN ('Completed', 'Cancelled', 'Closed')
		ORDER BY dn.posting_date ASC
		LIMIT 10
	""", as_dict=1)

	result = []
	for r in rows:
		days_pending = (getdate(nowdate()) - getdate(r.posting_date)).days if r.posting_date else 0
		result.append({
			"name": r.name,
			"customer": r.customer,
			"customer_name": r.customer_name or r.customer,
			"posting_date": str(r.posting_date) if r.posting_date else "",
			"days_pending": days_pending,
			"value": flt(r.grand_total),
			"per_billed": flt(r.per_billed),
			"status": r.status,
		})
	return result


def get_financial_leakage():
	"""Key financial leakage indicators."""
	items = []

	# Unsubmitted Stock Entries of type Manufacture (pending booking)
	pending_mfg_se = frappe.db.sql("""
		SELECT COUNT(*) as cnt, SUM(total_outgoing_value) as val
		FROM `tabStock Entry`
		WHERE stock_entry_type = 'Manufacture' AND docstatus = 0
	""", as_dict=1)
	if pending_mfg_se and pending_mfg_se[0].cnt:
		items.append({
			"issue": "Manufacture Entries (Draft)",
			"count": pending_mfg_se[0].cnt or 0,
			"value": flt(pending_mfg_se[0].val),
			"owner": "Production",
			"severity": "red",
		})

	# Delivered Not Invoiced (DN submitted, no SI)
	dni_row = frappe.db.sql("""
		SELECT COUNT(*) as cnt, SUM(grand_total) as val
		FROM `tabDelivery Note`
		WHERE docstatus = 1 AND per_billed < 100
		  AND status NOT IN ('Cancelled', 'Closed')
	""", as_dict=1)
	if dni_row and dni_row[0].cnt:
		items.append({
			"issue": "Delivered Not Invoiced",
			"count": dni_row[0].cnt or 0,
			"value": flt(dni_row[0].val),
			"owner": "Accounts",
			"severity": "red",
		})

	# Overdue Sales Orders
	overdue_so = frappe.db.sql("""
		SELECT COUNT(*) as cnt, SUM(grand_total) as val
		FROM `tabSales Order`
		WHERE docstatus = 1
		  AND delivery_date < %(today)s
		  AND per_delivered < 100
		  AND status NOT IN ('Completed', 'Cancelled', 'Closed')
	""", {"today": nowdate()}, as_dict=1)
	if overdue_so and overdue_so[0].cnt:
		items.append({
			"issue": "Overdue Sales Orders",
			"count": overdue_so[0].cnt or 0,
			"value": flt(overdue_so[0].val),
			"owner": "Sales + Production",
			"severity": "amber",
		})

	# Open Purchase Receipts not billed
	pr_not_billed = frappe.db.sql("""
		SELECT COUNT(*) as cnt, SUM(grand_total) as val
		FROM `tabPurchase Receipt`
		WHERE docstatus = 1 AND per_billed < 100
		  AND status NOT IN ('Completed', 'Cancelled', 'Closed')
	""", as_dict=1)
	if pr_not_billed and pr_not_billed[0].cnt:
		items.append({
			"issue": "Purchase Receipts Not Billed",
			"count": pr_not_billed[0].cnt or 0,
			"value": flt(pr_not_billed[0].val),
			"owner": "Purchase / Accounts",
			"severity": "amber",
		})

	return items


# ─────────────────────────────────────────────
#  DASHBOARD 4 — DELIVERY TIMELINE
# ─────────────────────────────────────────────

@frappe.whitelist()
def get_delivery_timeline():
	"""
	Per-Sales-Order delivery delay view.

	For every active (non-completed) SO:
	  - expected_date  : SO delivery_date (the BPP-committed date)
	  - progress_pct   : produced_qty / qty across all Work Orders
	  - predicted_date : projected completion based on current production pace
	                     (falls back to max planned_end_date when no pace data)
	  - delay_days     : predicted_date − expected_date  (positive = late)
	  - priority       : CRITICAL / AT RISK / WATCH / ON TRACK

	Sorted: worst delay first.
	"""
	today_date = getdate(nowdate())

	# ── 1. Fetch all active SOs ──────────────────────────────────────────
	sales_orders = frappe.db.sql("""
		SELECT
			so.name,
			so.customer,
			so.customer_name,
			so.delivery_date,
			so.grand_total,
			so.status,
			so.per_delivered,
			so.transaction_date
		FROM `tabSales Order` so
		WHERE so.docstatus = 1
		  AND so.status NOT IN ('Completed', 'Cancelled', 'Closed')
		  AND so.per_delivered < 100
		  AND so.delivery_date IS NOT NULL
		ORDER BY so.delivery_date ASC
		LIMIT 200
	""", as_dict=1)

	if not sales_orders:
		return []

	so_names = [so.name for so in sales_orders]
	so_names_set = set(so_names)

	# ── 1.5. Batch-fetch Production Plans linked to these SOs ────────────
	# SFG Work Orders have production_plan set but sales_order may be null,
	# so we need the PP→SO mapping to attribute them back correctly.
	pp_link_rows = frappe.db.sql("""
		SELECT ppso.sales_order, pp.name AS pp_name
		FROM `tabProduction Plan` pp
		INNER JOIN `tabProduction Plan Sales Order` ppso ON ppso.parent = pp.name
		WHERE ppso.sales_order IN %(so_names)s
		  AND pp.docstatus = 1
	""", {"so_names": tuple(so_names)}, as_dict=1)

	pp_to_so = {}   # pp_name → first matching SO name
	pp_names_all = []
	so_has_pp = set()  # SO names that have at least one Production Plan
	for row in pp_link_rows:
		so_has_pp.add(row.sales_order)
		if row.pp_name not in pp_to_so:
			pp_to_so[row.pp_name] = row.sales_order
			pp_names_all.append(row.pp_name)

	# ── 2. Batch-fetch Work Orders (FG via sales_order, SFG via production_plan) ─
	if pp_names_all:
		wo_where = "(wo.sales_order IN %(so_names)s OR wo.production_plan IN %(pp_names)s)"
		wo_params = {"so_names": tuple(so_names), "pp_names": tuple(pp_names_all)}
	else:
		wo_where = "wo.sales_order IN %(so_names)s"
		wo_params = {"so_names": tuple(so_names)}

	wo_rows = frappe.db.sql(f"""
		SELECT
			wo.sales_order,
			wo.production_plan,
			wo.name,
			wo.status,
			wo.production_item,
			wo.qty,
			wo.produced_qty,
			wo.planned_start_date,
			wo.planned_end_date,
			wo.actual_start_date,
			wo.actual_end_date
		FROM `tabWork Order` wo
		WHERE {wo_where}
		  AND wo.docstatus != 2
	""", wo_params, as_dict=1)

	wos_by_so = {}
	seen_wo = set()
	for w in wo_rows:
		if w.name in seen_wo:
			continue
		# FG WOs have sales_order in our set; SFG WOs are looked up via PP
		so_name = (
			w.sales_order if (w.sales_order and w.sales_order in so_names_set)
			else pp_to_so.get(w.production_plan)
		)
		if so_name and so_name in so_names_set:
			seen_wo.add(w.name)
			wos_by_so.setdefault(so_name, []).append(w)

	# ── 3a. Batch-fetch JC counts per WO ────────────────────────────────
	all_wo_names = list(seen_wo)
	jc_counts_by_wo = {}
	if all_wo_names:
		jc_rows = frappe.db.sql("""
			SELECT work_order,
			       COUNT(*) AS total,
			       SUM(CASE WHEN status='Completed' THEN 1 ELSE 0 END) AS done
			FROM `tabJob Card`
			WHERE work_order IN %(wn)s AND docstatus != 2
			GROUP BY work_order
		""", {"wn": tuple(all_wo_names)}, as_dict=1)
		for jc in jc_rows:
			jc_counts_by_wo[jc.work_order] = {"total": int(jc.total), "done": int(jc.done)}

	# ── 3. Batch-fetch items (first 2 per SO for display) ───────────────
	item_rows = frappe.db.sql("""
		SELECT parent, item_code, item_name, qty
		FROM `tabSales Order Item`
		WHERE parent IN %(so_names)s
		ORDER BY parent, idx
	""", {"so_names": tuple(so_names)}, as_dict=1)

	items_by_so = {}
	fg_items_by_so = {}  # so_name → set of item_codes ordered (FG items)
	for it in item_rows:
		items_by_so.setdefault(it.parent, []).append(it)
		fg_items_by_so.setdefault(it.parent, set()).add(it.item_code)

	# ── 4. Compute delay metrics per SO ─────────────────────────────────
	result = []
	for so in sales_orders:
		delivery_dt = getdate(so.delivery_date)
		wo_list = wos_by_so.get(so.name, [])
		so_items = items_by_so.get(so.name, [])

		# Aggregate production numbers
		total_qty = sum(flt(w.qty) for w in wo_list)
		total_produced = sum(flt(w.produced_qty) for w in wo_list)
		progress_pct = round((total_produced / total_qty) * 100) if total_qty > 0 else 0

		# Latest planned completion across all WOs
		planned_end_dates = [getdate(w.planned_end_date) for w in wo_list if w.planned_end_date]
		planned_completion = max(planned_end_dates) if planned_end_dates else None

		# Pace-based prediction
		predicted_completion = None
		delay_source = "none"

		for w in wo_list:
			if w.status not in ("In Process", "Not Started"):
				continue
			prod_qty = flt(w.produced_qty)
			rem_qty = flt(w.qty) - prod_qty

			if rem_qty <= 0:
				continue  # this WO is done

			if w.actual_start_date and prod_qty > 0:
				days_elapsed = max((today_date - getdate(w.actual_start_date)).days, 1)
				daily_rate = prod_qty / days_elapsed
				days_to_finish = math.ceil(rem_qty / daily_rate)
				wo_predicted = today_date + timedelta(days=days_to_finish)
			elif w.planned_end_date:
				# No production started yet — use planned end date
				wo_predicted = getdate(w.planned_end_date)
			else:
				continue

			if predicted_completion is None or wo_predicted > predicted_completion:
				predicted_completion = wo_predicted
				delay_source = "pace" if (w.actual_start_date and prod_qty > 0) else "plan"

		# Fall back to planned completion if no in-process WOs gave a prediction
		if predicted_completion is None and planned_completion:
			predicted_completion = planned_completion
			delay_source = "plan"

		# If no WOs at all, flag as "no production started"
		if predicted_completion is None:
			# No WOs created yet — just compare today vs delivery_date
			delay_days = (today_date - delivery_dt).days if today_date > delivery_dt else 0
			delay_source = "overdue" if delay_days > 0 else "no_wo"
		else:
			delay_days = (predicted_completion - delivery_dt).days

		# ── Priority scoring ─────────────────────────────────────────────
		actual_overdue = max(0, (today_date - delivery_dt).days)

		if actual_overdue > 0 and progress_pct < 100:
			priority = "CRITICAL"
			priority_sort = 1000 + delay_days
		elif delay_days > 0:
			priority = "AT RISK"
			priority_sort = 500 + delay_days
		elif planned_completion and (delivery_dt - planned_completion).days <= 2:
			priority = "WATCH"
			priority_sort = 100
		else:
			priority = "ON TRACK"
			priority_sort = max(0, -delay_days)

		# Build display items string
		item_labels = []
		for it in so_items[:2]:
			label = it.item_name if it.item_name else it.item_code
			item_labels.append(label)
		if len(so_items) > 2:
			item_labels.append(f"+{len(so_items) - 2} more")
		items_display = " · ".join(item_labels)

		# ── 5-stage pipeline: Sales Order → Prod Plan → Work Order → Job Card → Delivery
		fg_items = fg_items_by_so.get(so.name, set())
		fg_wos   = [w for w in wo_list if w.production_item in fg_items]

		jc_total_all = sum(jc_counts_by_wo.get(w.name, {}).get("total", 0) for w in wo_list)

		stage_pp  = 1 if so.name in so_has_pp else 0
		stage_wo  = 1 if len(wo_list) > 0 else 0
		stage_jc  = 1 if jc_total_all > 0 else 0
		stage_dn  = 1 if flt(so.per_delivered) > 0 else 0
		# Stage 1 (Sales Order) is always complete once we see the SO
		stages_done  = 1 + stage_pp + stage_wo + stage_jc + stage_dn
		stages_total = 5

		# Current stage label
		_stage_labels = ['Sales Order', 'Prod Plan', 'Work Order', 'Job Card', 'Delivery']
		current_stage = _stage_labels[stages_done - 1]

		# Job Execution = FG produced qty vs FG total qty (what gets delivered)
		fg_total_qty    = sum(flt(w.qty) for w in fg_wos)
		fg_produced_qty = sum(flt(w.produced_qty) for w in fg_wos)
		fg_progress_pct = round((fg_produced_qty / fg_total_qty) * 100) if fg_total_qty > 0 else 0

		result.append({
			"name": so.name,
			"customer": so.customer,
			"customer_name": so.customer_name or so.customer,
			"expected_date": str(delivery_dt),
			"predicted_date": str(predicted_completion) if predicted_completion else None,
			"delay_days": delay_days,
			"actual_overdue_days": actual_overdue,
			"progress_pct": progress_pct,
			"total_qty": flt(total_qty),
			"produced_qty": flt(total_produced),
			"wo_count": len(wo_list),
			"stages_done": stages_done,
			"stages_total": stages_total,
			"current_stage": current_stage,
			"fg_produced_qty": fg_produced_qty,
			"fg_total_qty": fg_total_qty,
			"fg_progress_pct": fg_progress_pct,
			"value": flt(so.grand_total),
			"status": so.status,
			"delay_source": delay_source,
			"priority": priority,
			"priority_sort": priority_sort,
			"items_display": items_display,
		})

	# Sort: worst first
	result.sort(key=lambda r: -r["priority_sort"])
	return result


@frappe.whitelist()
def get_so_timeline_detail(sales_order):
	"""
	Full production tree for the SO popup in Delivery Timeline.

	Returns FG and SFG Work Orders (with delay and RM status per WO),
	SO items, and Delivery Notes — everything needed to pinpoint where
	the delay originates in the FG → SFG → RM chain.
	"""
	today_date = getdate(nowdate())

	so = frappe.db.get_value("Sales Order", sales_order, [
		"name", "customer", "customer_name", "delivery_date",
		"grand_total", "status", "per_delivered", "transaction_date"
	], as_dict=1)
	if not so:
		return None

	# FG items directly on the SO
	so_items = frappe.db.sql("""
		SELECT item_code, item_name, qty, delivered_qty, stock_uom
		FROM `tabSales Order Item`
		WHERE parent = %(so)s ORDER BY idx
	""", {"so": sales_order}, as_dict=1)
	fg_item_codes = {it.item_code for it in so_items}

	# Production Plans linked to this SO (to catch SFG WOs that may not have sales_order set)
	prod_plans = frappe.db.sql("""
		SELECT DISTINCT pp.name FROM `tabProduction Plan` pp
		INNER JOIN `tabProduction Plan Sales Order` ppso ON ppso.parent = pp.name
		WHERE ppso.sales_order = %(so)s AND pp.docstatus = 1
	""", {"so": sales_order}, pluck="name")

	# All Work Orders: directly linked OR via production plan
	wo_cond = "wo.sales_order = %(so)s"
	wo_params = {"so": sales_order}
	if prod_plans:
		wo_cond = f"(wo.sales_order = %(so)s OR wo.production_plan IN %(pp_names)s)"
		wo_params["pp_names"] = tuple(prod_plans)

	work_orders = frappe.db.sql(f"""
		SELECT
			wo.name, wo.production_item, wo.qty, wo.produced_qty,
			wo.status, wo.docstatus, wo.planned_start_date, wo.planned_end_date,
			wo.actual_start_date, wo.actual_end_date,
			wo.sales_order, wo.production_plan,
			item.item_name AS item_name_display
		FROM `tabWork Order` wo
		LEFT JOIN `tabItem` item ON item.name = wo.production_item
		WHERE wo.docstatus != 2 AND {wo_cond}
		ORDER BY wo.planned_start_date
	""", wo_params, as_dict=1)

	wo_names = [w.name for w in work_orders]

	# Batch: Job Cards per WO (brief — just enough for the popup summary)
	jc_by_wo = {}
	if wo_names:
		jcs = frappe.db.sql("""
			SELECT work_order, name, operation, workstation, status, docstatus,
				   expected_end_date, actual_start_date, actual_end_date,
				   total_time_in_mins, for_quantity, total_completed_qty, remarks, idx
			FROM `tabJob Card`
			WHERE work_order IN %(wn)s AND docstatus != 2
			ORDER BY work_order, idx
		""", {"wn": tuple(wo_names)}, as_dict=1)
		for jc in jcs:
			jc_by_wo.setdefault(jc.work_order, []).append(jc)

	# Batch: pause reasons from Job Card Time Log (latest per JC)
	pause_reason_by_jc = {}
	all_jc_names = [jc.name for jcs_list in jc_by_wo.values() for jc in jcs_list]
	if all_jc_names:
		try:
			pause_rows = frappe.db.sql("""
				SELECT parent, custom_pause_reason AS pause_reason
				FROM `tabJob Card Time Log`
				WHERE parent IN %(jc_names)s
				  AND custom_pause_reason IS NOT NULL AND custom_pause_reason != ''
				ORDER BY parent, from_time DESC
			""", {"jc_names": tuple(all_jc_names)}, as_dict=1)
			for row in pause_rows:
				if row.parent not in pause_reason_by_jc:
					pause_reason_by_jc[row.parent] = row.pause_reason
		except Exception:
			pass

	# Batch: RM items per WO
	rm_by_wo = {}
	if wo_names:
		rms = frappe.db.sql("""
			SELECT parent AS work_order, item_code, item_name,
				   required_qty, transferred_qty,
				   available_qty_at_wip_warehouse, stock_uom
			FROM `tabWork Order Item`
			WHERE parent IN %(wn)s
			ORDER BY parent, idx
		""", {"wn": tuple(wo_names)}, as_dict=1)
		for rm in rms:
			rm_by_wo.setdefault(rm.work_order, []).append(rm)

	# Delivery Notes
	delivery_dt = getdate(so.delivery_date) if so.delivery_date else None
	dns = frappe.db.sql("""
		SELECT DISTINCT dn.name, dn.posting_date, dn.status,
			   dn.grand_total, dn.per_billed
		FROM `tabDelivery Note` dn
		INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dni.against_sales_order = %(so)s AND dn.docstatus != 2
		ORDER BY dn.posting_date DESC
	""", {"so": sales_order}, as_dict=1)

	# Enrich each Work Order
	enriched_wos = []
	for w in work_orders:
		is_fg = w.production_item in fg_item_codes
		total_qty = flt(w.qty)
		produced = flt(w.produced_qty)
		progress = round((produced / total_qty) * 100) if total_qty > 0 else 0

		predicted_date = None
		delay_source = "none"

		if w.actual_start_date and produced > 0 and w.status == "In Process":
			days_elapsed = max((today_date - getdate(w.actual_start_date)).days, 1)
			daily_rate = produced / days_elapsed
			remaining = total_qty - produced
			if daily_rate > 0 and remaining > 0:
				days_to_finish = math.ceil(remaining / daily_rate)
				predicted_date = today_date + timedelta(days=days_to_finish)
				delay_source = "pace"

		if predicted_date is None and w.planned_end_date:
			predicted_date = getdate(w.planned_end_date)
			delay_source = "plan"

		delay_days = 0
		if predicted_date and delivery_dt:
			delay_days = (predicted_date - delivery_dt).days

		# RM summary flags
		rm_items = rm_by_wo.get(w.name, [])
		rm_issues = [
			rm for rm in rm_items
			if flt(rm.transferred_qty) < flt(rm.required_qty)
		]

		# Job card counts
		jcs = jc_by_wo.get(w.name, [])
		jc_done = sum(1 for jc in jcs if jc.status == "Completed")
		jc_total = len(jcs)

		enriched_wos.append({
			"name": w.name,
			"production_item": w.production_item,
			"item_name": w.item_name_display or w.production_item,
			"is_fg": is_fg,
			"wo_type": "FG" if is_fg else "SFG",
			"qty": total_qty,
			"produced_qty": produced,
			"progress_pct": progress,
			"status": w.status,
			"planned_start_date": str(w.planned_start_date) if w.planned_start_date else None,
			"planned_end_date": str(w.planned_end_date) if w.planned_end_date else None,
			"actual_start_date": str(w.actual_start_date) if w.actual_start_date else None,
			"actual_end_date": str(w.actual_end_date) if w.actual_end_date else None,
			"predicted_date": str(predicted_date) if predicted_date else None,
			"delay_days": delay_days,
			"delay_source": delay_source,
			"rm_issue_count": len(rm_issues),
			"rm_total_count": len(rm_items),
			"rm_items": [dict(rm) for rm in rm_items],
			"jc_done": jc_done,
			"jc_total": jc_total,
			"job_cards": [{
				"name": jc.name,
				"operation": jc.operation,
				"workstation": jc.workstation,
				"status": jc.status,
				"docstatus": jc.docstatus,
				"expected_end_date": str(jc.expected_end_date) if jc.expected_end_date else None,
				"actual_start_date": str(jc.actual_start_date) if jc.actual_start_date else None,
				"actual_end_date": str(jc.actual_end_date) if jc.actual_end_date else None,
				"total_time_in_mins": flt(jc.total_time_in_mins),
				"for_quantity": flt(jc.for_quantity),
				"total_completed_qty": flt(jc.total_completed_qty),
				"remarks": jc.remarks or "",
				"pause_reason": pause_reason_by_jc.get(jc.name, ""),
			} for jc in jcs],
			"docstatus": w.docstatus,
		})

	# Sort: FG first, then SFG; within each: In Process → Not Started → Draft → others → Completed → Stopped
	_WO_STATUS_RANK = {"In Process": 0, "Not Started": 1, "Completed": 4, "Stopped": 5}
	enriched_wos.sort(key=lambda w: (
		0 if w["is_fg"] else 1,
		2 if w.get("docstatus", 1) == 0 else _WO_STATUS_RANK.get(w["status"], 3),
		-w["delay_days"],
	))

	return {
		"sales_order": {
			"name": so.name,
			"customer": so.customer,
			"customer_name": so.customer_name or so.customer,
			"delivery_date": str(so.delivery_date) if so.delivery_date else None,
			"grand_total": flt(so.grand_total),
			"status": so.status,
			"per_delivered": flt(so.per_delivered),
		},
		"so_items": [dict(it) for it in so_items],
		"work_orders": enriched_wos,
		"delivery_notes": [{
			"name": dn.name,
			"posting_date": str(dn.posting_date) if dn.posting_date else None,
			"status": dn.status,
			"grand_total": flt(dn.grand_total),
			"per_billed": flt(dn.per_billed),
		} for dn in dns],
	}


@frappe.whitelist()
def get_wo_timeline_detail(work_order):
	"""
	Work Order detail popup — Job Cards, RM items, Stock Entries, delay.
	"""
	today_date = getdate(nowdate())

	wo = frappe.db.get_value("Work Order", work_order, [
		"name", "production_item", "qty", "produced_qty", "status",
		"planned_start_date", "planned_end_date",
		"actual_start_date", "actual_end_date",
		"sales_order", "production_plan"
	], as_dict=1)
	if not wo:
		return None

	item_name = frappe.db.get_value("Item", wo.production_item, "item_name") or wo.production_item

	# Job Cards (full detail)
	job_cards = frappe.db.sql("""
		SELECT name, operation, workstation, status, docstatus,
			   expected_start_date, expected_end_date,
			   actual_start_date, actual_end_date,
			   total_time_in_mins, for_quantity, total_completed_qty, remarks, idx
		FROM `tabJob Card`
		WHERE work_order = %(wo)s AND docstatus != 2
		ORDER BY idx
	""", {"wo": work_order}, as_dict=1)

	# RM items
	rm_items = frappe.db.sql("""
		SELECT item_code, item_name, required_qty, transferred_qty,
			   available_qty_at_wip_warehouse, stock_uom
		FROM `tabWork Order Item`
		WHERE parent = %(wo)s ORDER BY idx
	""", {"wo": work_order}, as_dict=1)

	# Stock Entries
	stock_entries = frappe.db.sql("""
		SELECT name, stock_entry_type, posting_date, docstatus,
			   CASE docstatus WHEN 1 THEN 'Submitted' WHEN 0 THEN 'Draft' ELSE 'Cancelled' END AS status
		FROM `tabStock Entry`
		WHERE work_order = %(wo)s AND docstatus != 2
		ORDER BY posting_date DESC
	""", {"wo": work_order}, as_dict=1)

	# Delay calc for this WO
	total_qty = flt(wo.qty)
	produced = flt(wo.produced_qty)
	progress = round((produced / total_qty) * 100) if total_qty > 0 else 0

	predicted_date = None
	delay_days = 0
	delay_source = "none"

	if wo.actual_start_date and produced > 0 and wo.status == "In Process":
		days_elapsed = max((today_date - getdate(wo.actual_start_date)).days, 1)
		daily_rate = produced / days_elapsed
		remaining = total_qty - produced
		if daily_rate > 0 and remaining > 0:
			days_to_finish = math.ceil(remaining / daily_rate)
			predicted_date = today_date + timedelta(days=days_to_finish)
			delay_source = "pace"

	if predicted_date is None and wo.planned_end_date:
		predicted_date = getdate(wo.planned_end_date)
		delay_source = "plan"

	# Delay relative to WO's own planned_end_date
	if predicted_date and wo.planned_end_date:
		delay_days = (predicted_date - getdate(wo.planned_end_date)).days

	# Pause reasons from Job Card Time Log (latest per JC)
	wo_pause_reason_by_jc = {}
	jc_names = [jc.name for jc in job_cards]
	if jc_names:
		try:
			wo_pause_rows = frappe.db.sql("""
				SELECT parent, custom_pause_reason AS pause_reason
				FROM `tabJob Card Time Log`
				WHERE parent IN %(jc_names)s
				  AND custom_pause_reason IS NOT NULL AND custom_pause_reason != ''
				ORDER BY parent, from_time DESC
			""", {"jc_names": tuple(jc_names)}, as_dict=1)
			for row in wo_pause_rows:
				if row.parent not in wo_pause_reason_by_jc:
					wo_pause_reason_by_jc[row.parent] = row.pause_reason
		except Exception:
			pass

	# Enrich job cards
	enriched_jcs = []
	for jc in job_cards:
		jc_overdue = 0
		if jc.expected_end_date and jc.status not in ("Completed",):
			jc_overdue = max(0, (today_date - getdate(jc.expected_end_date)).days)
		enriched_jcs.append({
			"name": jc.name,
			"operation": jc.operation or "—",
			"workstation": jc.workstation or "—",
			"status": jc.status,
			"docstatus": jc.docstatus,
			"expected_start_date": str(jc.expected_start_date) if jc.expected_start_date else None,
			"expected_end_date": str(jc.expected_end_date) if jc.expected_end_date else None,
			"actual_start_date": str(jc.actual_start_date) if jc.actual_start_date else None,
			"actual_end_date": str(jc.actual_end_date) if jc.actual_end_date else None,
			"total_time_in_mins": flt(jc.total_time_in_mins),
			"for_quantity": flt(jc.for_quantity),
			"total_completed_qty": flt(jc.total_completed_qty),
			"remarks": jc.remarks or "",
			"pause_reason": wo_pause_reason_by_jc.get(jc.name, ""),
			"days_overdue": jc_overdue,
		})

	return {
		"work_order": {
			"name": wo.name,
			"production_item": wo.production_item,
			"item_name": item_name,
			"qty": total_qty,
			"produced_qty": produced,
			"progress_pct": progress,
			"status": wo.status,
			"planned_start_date": str(wo.planned_start_date) if wo.planned_start_date else None,
			"planned_end_date": str(wo.planned_end_date) if wo.planned_end_date else None,
			"actual_start_date": str(wo.actual_start_date) if wo.actual_start_date else None,
			"actual_end_date": str(wo.actual_end_date) if wo.actual_end_date else None,
			"predicted_date": str(predicted_date) if predicted_date else None,
			"delay_days": delay_days,
			"delay_source": delay_source,
			"sales_order": wo.sales_order,
		},
		"job_cards": enriched_jcs,
		"rm_items": [dict(rm) for rm in rm_items],
		"stock_entries": [{
			"name": se.name,
			"stock_entry_type": se.stock_entry_type,
			"posting_date": str(se.posting_date) if se.posting_date else None,
			"status": se.status,
		} for se in stock_entries],
	}
