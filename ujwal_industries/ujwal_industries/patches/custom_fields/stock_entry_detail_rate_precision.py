import frappe


def execute():
	# The annexure rate fetched onto "Send to Subcontractor" rows (Net RM
	# Cost/Pc + cumulative operation rates) is a per-piece figure that often
	# needs more than the system's default currency precision (commonly 2,
	# sometimes 0) to display without misleading rounding — e.g. 1.30515
	# showing as 1 or 2. Force explicit precision on these two fields so the
	# UI always shows the real stored value regardless of System Settings.
	for fieldname in ("basic_rate", "valuation_rate"):
		frappe.make_property_setter(
			{
				"doctype": "Stock Entry Detail",
				"fieldname": fieldname,
				"property": "precision",
				"value": "3",
				"property_type": "Select",
			},
			validate_fields_for_doctype=False,
		)
