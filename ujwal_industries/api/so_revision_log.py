import frappe


@frappe.whitelist()
def log_revision(doctype=None, docname=None, reason=None, sales_order=None, purchase_order=None):
	doctype, docname = _resolve_target(doctype, docname, sales_order, purchase_order)
	if not (doctype and docname and reason):
		return

	version_name = frappe.db.get_value(
		"Version",
		{"ref_doctype": doctype, "docname": docname},
		"name",
		order_by="creation desc",
	)
	if not version_name:
		return

	version = frappe.get_doc("Version", version_name)
	data = frappe.parse_json(version.data or "{}")
	data["reason"] = reason
	version.db_set("data", frappe.as_json(data), update_modified=False)


def _resolve_target(doctype, docname, sales_order=None, purchase_order=None):
	if doctype and docname:
		return doctype, docname

	if sales_order:
		return "Sales Order", sales_order

	if purchase_order:
		return "Purchase Order", purchase_order

	return doctype, docname
