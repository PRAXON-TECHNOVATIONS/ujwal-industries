import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


APPROVAL_FIELDS = [
	{
		"fieldname": "custom_update_approval_status",
		"fieldtype": "Select",
		"label": "Update Approval Status",
		"options": "\nPending Approval\nApproved",
		"allow_on_submit": 1,
		"hidden": 1,
		"read_only": 1,
		"no_copy": 1,
		"print_hide": 1,
		"print_hide_if_no_value": 1,
		"report_hide": 1,
		"insert_after": "taxable_value",
	},
	{
		"fieldname": "custom_update_request_reason",
		"fieldtype": "Small Text",
		"label": "Update Request Reason",
		"allow_on_submit": 1,
		"hidden": 1,
		"read_only": 1,
		"no_copy": 1,
		"print_hide": 1,
		"print_hide_if_no_value": 1,
		"report_hide": 1,
		"insert_after": "custom_update_approval_status",
	},
	{
		"fieldname": "custom_update_request_data",
		"fieldtype": "Long Text",
		"label": "Update Request Data",
		"allow_on_submit": 1,
		"hidden": 1,
		"read_only": 1,
		"no_copy": 1,
		"print_hide": 1,
		"print_hide_if_no_value": 1,
		"report_hide": 1,
		"insert_after": "custom_update_request_reason",
	},
]


def create_fields():
	for doctype in ("Sales Order Item", "Purchase Order Item"):
		for field in APPROVAL_FIELDS:
			if not frappe.db.exists("Custom Field", f"{doctype}-{field['fieldname']}"):
				create_custom_field(doctype, field)
