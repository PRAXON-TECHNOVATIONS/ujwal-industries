import frappe
from frappe.utils import add_days, nowdate


@frappe.whitelist()
def get_machine_production_data():
	"""Return active job cards (planned within -inf..today+3) grouped by workstation/machine."""
	window_end = add_days(nowdate(), 3)

	rows = frappe.db.sql(
		"""
		SELECT
			jc.name            AS job_card,
			jc.workstation     AS machine_no,
			ws.custom_asset AS machine_name,
			jc.work_order      AS work_order,
			jc.production_item AS item_code,
			jc.item_name       AS item_name,
			jc.status          AS status,
			jc.expected_start_date,
			jc.expected_end_date,
			jc.actual_start_date,
			jc.for_quantity    AS planned_qty,
			jc.total_completed_qty AS completed_qty,
			wo.sales_order     AS sales_order,
			wo.planned_start_date  AS wo_planned_start,
			wo.planned_end_date    AS wo_planned_end
		FROM `tabJob Card` jc
		LEFT JOIN `tabWork Order` wo ON wo.name = jc.work_order
		LEFT JOIN `tabWorkstation` ws ON ws.name = jc.workstation
		WHERE
			jc.docstatus != 2
			AND jc.status NOT IN ('Completed', 'Cancelled')
			AND DATE(COALESCE(jc.expected_start_date, wo.planned_start_date)) <= %(window_end)s
		ORDER BY jc.workstation, jc.expected_start_date
		""",
		{"window_end": window_end},
		as_dict=True,
	)

	# Group by machine
	machines = {}
	for row in rows:
		key = row.machine_no or "Unknown"
		if key not in machines:
			machines[key] = {
				"machine_no": key,
				"machine_name": key,
				"jobs": [],
			}
		machines[key]["jobs"].append(row)

	return list(machines.values())
