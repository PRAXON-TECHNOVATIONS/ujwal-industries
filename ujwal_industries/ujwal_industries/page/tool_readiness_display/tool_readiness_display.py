import frappe

from ujwal_industries.ujwal_industries.api.bom_tool_data import get_tool_readiness_rows


@frappe.whitelist()
def get_tool_readiness_data():
	"""Return one row per FG + Tool that has a genuinely upcoming Production
	Plan need, sorted so the most urgent (lowest remaining days) tools come
	first. Tools with no upcoming PP date are left out entirely.
	"""
	rows = get_tool_readiness_rows()
	rows.sort(key=lambda r: r["remaining_days"])
	return rows
