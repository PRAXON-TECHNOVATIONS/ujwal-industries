import frappe
from frappe.utils import add_days, flt, getdate, nowdate


@frappe.whitelist()
def get_store_display_data():
	"""Return one row per active Work Order (start date within ..today+3) with material and JC roll-up.

	Completed / Stopped / Closed Work Orders are excluded so a WO drops off the
	display once all FG qty has been received (ERPNext marks it Completed then).
	Overdue WOs stay visible because their start date is already <= today+3.
	"""
	window_end = add_days(nowdate(), 3)

	work_orders = frappe.db.sql(
		"""
		SELECT
			wo.name				AS work_order,
			wo.planned_start_date,
			wo.planned_end_date,
			wo.production_item	AS part_no,
			wo.item_name		AS part_name,
			wo.qty				AS wo_qty,
			wo.produced_qty		AS wo_received_qty,
			wo.status			AS wo_status
		FROM `tabWork Order` wo
		WHERE
			wo.docstatus IN (0, 1)
			AND wo.status NOT IN ('Completed', 'Stopped', 'Closed')
			AND DATE(wo.planned_start_date) <= %(window_end)s
		ORDER BY wo.planned_end_date ASC, wo.name ASC
		""",
		{"window_end": window_end},
		as_dict=True,
	)

	if not work_orders:
		return []

	wo_names = [wo.work_order for wo in work_orders]

	rm_by_wo = _get_raw_materials(wo_names)
	jc_by_wo = _get_job_card_rollup(wo_names)
	today = getdate(nowdate())

	rows = []
	for wo in work_orders:
		rm = rm_by_wo.get(wo.work_order, [])
		jc = jc_by_wo.get(wo.work_order) or frappe._dict()

		manufactured_qty = flt(jc.get("manufactured_qty"))
		wo_received_qty = flt(wo.wo_received_qty)
		balance_counting_qty = manufactured_qty - wo_received_qty

		# planned_end_date is carried onto the WO from the Production Plan (at creation
		# and preserved on submit), so read it directly here.
		end_date = wo.planned_end_date

		# Signed days vs planned end: >0 overdue (red), <=0 days remaining (green).
		delay_in_days = None
		if end_date:
			delay_in_days = (today - getdate(end_date)).days

		# A WO with no Job Cards yet falls back to its own status (e.g. Draft / Not Started).
		jo_status = jc.get("jo_status") or _wo_status_label(wo.wo_status)

		rows.append(
			{
				"work_order": wo.work_order,
				"wo_start_date": wo.planned_start_date,
				"wo_end_date": end_date,
				"part_no": wo.part_no,
				"part_name": wo.part_name,
				"raw_material_no": ", ".join(r.item_code for r in rm),
				"raw_material_name": ", ".join(r.item_name for r in rm),
				"wo_qty": wo.wo_qty,
				"wo_received_qty": wo_received_qty,
				"material_required_qty": sum(flt(r.required_qty) for r in rm),
				"material_issued_qty": sum(flt(r.transferred_qty) for r in rm),
				"manufactured_qty": manufactured_qty,
				"balance_counting_qty": balance_counting_qty,
				"scrap_qty": flt(jc.get("scrap_qty")),
				"scrap_rec_qty": flt(jc.get("scrap_rec_qty")),
				"jo_status": jo_status,
				"delay_in_days": delay_in_days,
			}
		)

	return rows


def _get_raw_materials(wo_names):
	items = frappe.db.sql(
		"""
		SELECT
			woi.parent			AS work_order,
			woi.item_code,
			woi.item_name,
			woi.required_qty,
			woi.transferred_qty
		FROM `tabWork Order Item` woi
		WHERE woi.parent IN %(work_orders)s
		ORDER BY woi.idx
		""",
		{"work_orders": wo_names},
		as_dict=True,
	)

	by_wo = {}
	for item in items:
		by_wo.setdefault(item.work_order, []).append(item)
	return by_wo


def _get_job_card_rollup(wo_names):
	"""Roll up Job Card qty/status/scrap per Work Order."""
	rows = frappe.db.sql(
		"""
		SELECT
			jc.work_order,
			SUM(jc.total_completed_qty)	AS manufactured_qty,
			GROUP_CONCAT(DISTINCT jc.status SEPARATOR '||')	AS jc_statuses
		FROM `tabJob Card` jc
		WHERE
			jc.work_order IN %(work_orders)s
			AND jc.docstatus != 2
		GROUP BY jc.work_order
		""",
		{"work_orders": wo_names},
		as_dict=True,
	)

	scrap_rows = frappe.db.sql(
		"""
		SELECT
			se.work_order,
			SUM(CASE WHEN sed.is_scrap_item = 1 THEN sed.qty ELSE 0 END)	AS scrap_qty
		FROM `tabStock Entry` se
		JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		WHERE
			se.work_order IN %(work_orders)s
			AND se.docstatus = 1
		GROUP BY se.work_order
		""",
		{"work_orders": wo_names},
		as_dict=True,
	)
	scrap_by_wo = {r.work_order: flt(r.scrap_qty) for r in scrap_rows}

	by_wo = {}
	for row in rows:
		statuses = [s for s in (row.get("jc_statuses") or "").split("||") if s]
		row["jo_status"] = _overall_status(statuses)
		row["scrap_qty"] = scrap_by_wo.get(row.work_order, 0)
		row["scrap_rec_qty"] = 0
		by_wo[row.work_order] = row
	return by_wo


def _wo_status_label(wo_status):
	"""Display label for a Work Order that has no Job Cards yet."""
	if wo_status == "Draft":
		return "Draft"
	if wo_status == "Not Started":
		return "Not Started"
	return wo_status or "Open"


def _overall_status(statuses):
	"""Collapse the per-operation Job Card statuses into one status for the WO.

	Priority (highest wins, so the most action-needing state surfaces):
	Material Return > On Hold > Work In Progress > Open > Completed.
	A WO is only "Completed" when every Job Card is Completed.
	"""
	if not statuses:
		return None

	unique = set(statuses)

	if all(s == "Completed" for s in unique):
		return "Completed"

	for priority in ("Material Return", "On Hold", "Work In Progress", "Open"):
		if priority in unique:
			return priority

	# Fallback: first non-completed status, else first status.
	for s in statuses:
		if s != "Completed":
			return s
	return statuses[0]
