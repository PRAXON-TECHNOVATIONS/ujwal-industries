import frappe


def execute():
	# Subcontract service rates fetched onto a "Job Work" PO row (e.g. Case
	# Hardening 0.5, Plating 0.15) are sub-rupee figures that the system's
	# default currency precision (commonly 0 or 2) rounds away entirely —
	# e.g. 0.5 showing as 0. Force explicit precision so the UI always shows
	# the real stored value regardless of System Settings.
	frappe.make_property_setter(
		{
			"doctype": "Purchase Order Item",
			"fieldname": "rate",
			"property": "precision",
			"value": "3",
			"property_type": "Select",
		},
		validate_fields_for_doctype=False,
	)
