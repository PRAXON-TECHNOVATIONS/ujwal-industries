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

