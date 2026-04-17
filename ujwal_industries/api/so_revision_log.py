import frappe


@frappe.whitelist()
def log_revision(sales_order, reason):
	version_name = frappe.db.get_value(
		"Version",
		{"ref_doctype": "Sales Order", "docname": sales_order},
		"name",
		order_by="creation desc",
	)
	if not version_name:
		return

	version = frappe.get_doc("Version", version_name)
	data = frappe.parse_json(version.data or "{}")
	data["reason"] = reason
	version.db_set("data", frappe.as_json(data), update_modified=False)
