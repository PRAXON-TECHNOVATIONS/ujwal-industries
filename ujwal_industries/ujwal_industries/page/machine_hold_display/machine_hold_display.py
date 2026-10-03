import frappe


@frappe.whitelist()
def get_machine_hold_data(pause_reasons=None):
	"""Return job cards currently On Hold (with their latest pause reason) grouped by workstation/machine.

	Optional multi-select filter: pause_reasons (latest pause reason).
	"""
	pause_reasons = set(frappe.parse_json(pause_reasons) or [])

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
			wo.planned_end_date    AS wo_planned_end,
			(
				SELECT tl.custom_pause_reason
				FROM `tabJob Card Time Log` tl
				WHERE tl.parent = jc.name
					AND tl.custom_pause_reason IS NOT NULL
					AND tl.custom_pause_reason != ''
				ORDER BY tl.from_time DESC
				LIMIT 1
			) AS pause_reason
		FROM `tabJob Card` jc
		LEFT JOIN `tabWork Order` wo ON wo.name = jc.work_order
		LEFT JOIN `tabWorkstation` ws ON ws.name = jc.workstation
		WHERE
			jc.docstatus != 2
			AND jc.status = 'On Hold'
		ORDER BY jc.workstation, jc.expected_start_date
		""",
		as_dict=True,
	)

	if pause_reasons:
		rows = [r for r in rows if r.pause_reason in pause_reasons]

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
