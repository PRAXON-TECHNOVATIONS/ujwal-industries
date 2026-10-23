import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def create_fields():
	# Mirrors Purchase Receipt's `remarks` (Small Text, More Info tab), but editable after submit.
	# Named custom_remarks so it isn't auto-mapped into the PR's own remarks on make_purchase_receipt.
	create_custom_field(
		"Purchase Order",
		{
			"fieldname": "custom_remarks",
			"fieldtype": "Small Text",
			"label": "Remarks",
			"allow_on_submit": 1,
			"no_copy": 1,
			"print_hide": 1,
			"insert_after": "inter_company_order_reference",
		},
	)
	frappe.clear_cache(doctype="Purchase Order")
