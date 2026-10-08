"""Support the operator-driven Material Return flow on the Job Card.

1. Add a "Material Return" option to the Job Card `status` Select field (via Property
   Setter) so the status can be set when the operator returns material mid-job.
2. Create a "Material Return" Job Card Pause Reason so the closing time log can carry it.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

STATUS_OPTIONS = "Open\nWork In Progress\nMaterial Transferred\nOn Hold\nMaterial Return\nSubmitted\nCancelled\nCompleted"


def execute():
	# 1. Extend the status field options.
	make_property_setter(
		"Job Card",
		"status",
		"options",
		STATUS_OPTIONS,
		"Text",
		validate_fields_for_doctype=False,
	)

	# 2. Ensure the pause reason master exists.
	if not frappe.db.exists("Job Card Pause Reason", "Material Return"):
		doc = frappe.new_doc("Job Card Pause Reason")
		doc.name1 = "Material Return"
		doc.insert(ignore_permissions=True)

	frappe.clear_cache(doctype="Job Card")
	frappe.db.commit()
