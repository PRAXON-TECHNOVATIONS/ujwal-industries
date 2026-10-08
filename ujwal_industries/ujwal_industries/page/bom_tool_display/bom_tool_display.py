import frappe

from ujwal_industries.ujwal_industries.api.bom_tool_data import get_bom_tool_rows

# Severity order so the most action-needing tools surface first by default.
STATUS_PRIORITY = {
	"Under Maintenance": 0,
	"Production Completed": 1,
	"Ready for Production": 2,
}


@frappe.whitelist()
def get_bom_tool_display_data(item=None, tool=None, status=None):
	filters = {
		"item": item,
		"tool": tool,
	}
	rows = get_bom_tool_rows(filters)

	if status:
		rows = [r for r in rows if r["status"] == status]

	rows.sort(key=lambda r: (STATUS_PRIORITY.get(r["status"], 99), r["fg_part_no"] or "", r["operation"] or ""))

	return rows
