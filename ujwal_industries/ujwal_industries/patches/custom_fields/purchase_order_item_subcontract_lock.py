import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Persisted per-row flag: once a user manually edits rate on a
	# subcontracting PO's "Job Work" row, the subcontract-rate auto-fetch
	# (single-operation Rate/Pc from the finished item's default Subcontract
	# row) must never touch that row again — including on a later reopen of
	# a still-draft order. Hidden, since it's bookkeeping for the client
	# script, not something a user should see or edit directly.
	create_custom_fields(
		{
			"Purchase Order Item": [
				{
					"fieldname": "custom_subcontract_rate_locked",
					"fieldtype": "Check",
					"label": "Subcontract Rate Locked",
					"insert_after": "rate",
					"hidden": 1,
					"default": "0",
					"no_copy": 1,
					"print_hide": 1,
				}
			]
		},
		ignore_validate=True,
	)
