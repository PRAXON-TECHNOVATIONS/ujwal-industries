import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Persisted per-row flag: once a user manually edits basic_rate on a
	# "Send to Subcontractor" row, the annexure auto-fetch (Net RM Cost/Pc +
	# cumulative operation rates from Cost Estimation) must never touch that
	# row again — including on a later reopen of a still-draft entry. Hidden,
	# since it's bookkeeping for the client script, not something a user
	# should see or edit directly.
	create_custom_fields(
		{
			"Stock Entry Detail": [
				{
					"fieldname": "custom_annexure_rate_locked",
					"fieldtype": "Check",
					"label": "Annexure Rate Locked",
					"insert_after": "basic_rate",
					"hidden": 1,
					"default": "0",
					"no_copy": 1,
					"print_hide": 1,
				}
			]
		},
		ignore_validate=True,
	)
