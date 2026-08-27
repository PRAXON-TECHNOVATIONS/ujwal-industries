import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.model.utils.rename_field import rename_field


def execute():
	# These two Workstation cost fields were named/labelled "per Day" but are
	# actually entered and used as per-shift figures — rename both the
	# fieldname and label to match, preserving existing data. rename_field()
	# only copies data into a fieldname whose Custom Field/column already
	# exists, so create the new fields first, copy data across, then drop
	# the old Custom Fields (real production workstations already have
	# nonzero values stored under the old names).
	renames = {
		"custom_wages_per_day": ("custom_wages_per_shift", "Wages per Shift"),
		"custom_electricity_per_day": ("custom_electricity_per_shift", "Electricity Charges per Shift"),
	}

	create_custom_fields(
		{
			"Workstation": [
				{
					"fieldname": new_fieldname,
					"fieldtype": "Float",
					"label": new_label,
					"precision": "3",
					"insert_after": old_fieldname,
				}
				for old_fieldname, (new_fieldname, new_label) in renames.items()
			]
		},
		ignore_validate=True,
	)

	for old_fieldname, (new_fieldname, _label) in renames.items():
		if frappe.db.has_column("Workstation", old_fieldname):
			rename_field("Workstation", old_fieldname, new_fieldname)

		old_custom_field = frappe.db.get_value(
			"Custom Field", {"dt": "Workstation", "fieldname": old_fieldname}, "name"
		)
		if old_custom_field:
			frappe.delete_doc("Custom Field", old_custom_field, ignore_permissions=True)

	frappe.clear_cache(doctype="Workstation")
