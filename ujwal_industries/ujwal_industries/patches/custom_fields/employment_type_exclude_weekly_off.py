import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Workers are paid only for days they work: weekly offs from the Holiday
	# List are dropped from Working Days and Payment Days on their Salary
	# Slips (31-day month with 4 weekly offs -> 27). Staff stay on the full
	# month as per Payroll Settings.
	create_custom_fields(
		{
			"Employment Type": [
				{
					"fieldname": "custom_exclude_weekly_off_from_working_days",
					"fieldtype": "Check",
					"label": "Exclude Weekly Off from Working Days",
					"insert_after": "employee_type_name",
					"default": "0",
					"description": "Salary Slips of employees with this type will not count Weekly Off days "
					"(from the Holiday List) in Working Days or Payment Days.",
				}
			]
		},
		ignore_validate=True,
	)

	frappe.db.set_value("Employment Type", "Worker", "custom_exclude_weekly_off_from_working_days", 1)
