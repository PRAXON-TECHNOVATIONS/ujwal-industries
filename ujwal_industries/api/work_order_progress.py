import frappe
from frappe.utils import flt

@frappe.whitelist()
def get_job_card_progress(work_order):
	jcs = frappe.get_all(
		"Job Card",
		filters={"work_order": work_order, "docstatus": ["<", 2]},
		fields=["status", "total_completed_qty", "for_quantity"]
	)

	completed = working = not_started = 0

	for jc in jcs:
		if jc.status == "Completed":
			completed += flt(jc.total_completed_qty)
		elif jc.status in ("Work In Progress", "On Hold"):
			working += flt(jc.for_quantity)
		if jc.status == "Open":
			not_started += flt(jc.for_quantity)

	return {
		"completed": completed,
		"working": working,
		"not_started": not_started
	}
 
@frappe.whitelist()
def get_operation_progress(work_order):
	job_cards = frappe.get_all(
		"Job Card",
		filters={
			"work_order": work_order,
			"docstatus": ["<", 2]
		},
		fields=[
			"operation",
			"status",
			"for_quantity",
			"total_completed_qty"
		]
	)

	operations = {}

	for jc in job_cards:
		op = jc.operation

		if op not in operations:
			operations[op] = {
				"total_qty": 0,
				"completed_qty": 0,
				"has_on_hold": False
			}

		operations[op]["total_qty"] += flt(jc.for_quantity)
		operations[op]["completed_qty"] += flt(jc.total_completed_qty)

		if jc.status == "On Hold":
			operations[op]["has_on_hold"] = True

	result = {
		"completed": [],
		"in_progress": [],
		"on_hold": [],
		"not_started": []
	}

	for op, d in operations.items():
		total = d["total_qty"]
		completed = d["completed_qty"]
		pct = (completed / total * 100) if total else 0

		if completed >= total and total > 0:
			result["completed"].append((op, 100))
		elif d["has_on_hold"]:
			result["on_hold"].append((op, pct))
		elif completed > 0:
			result["in_progress"].append((op, pct))
		else:
			result["not_started"].append((op, 0))

	return result
