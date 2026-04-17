import frappe


def execute():
	"""Patch entry point - creates custom fields for Customer"""
	create_fields()


def create_fields():
	"""Create MSME/GST Doc checkbox and attach fields for Customer"""

	fields_to_create = [
		{
			"fieldname": "custom_msme_gst_doc",
			"fieldtype": "Check",
			"label": "MSME/GST Doc",
			"default": "0",
			"insert_after": "pan",
		},
		{
			"fieldname": "custom_msme_doc",
			"fieldtype": "Attach",
			"label": "MSME",
			"depends_on": "eval:doc.custom_msme_gst_doc == 1",
			"insert_after": "custom_msme_gst_doc",
		},
		{
			"fieldname": "custom_gst_doc",
			"fieldtype": "Attach",
			"label": "GST",
			"depends_on": "eval:doc.custom_msme_gst_doc == 1",
			"insert_after": "custom_msme_doc",
		},
	]

	for df in fields_to_create:
		if frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": df["fieldname"]}):
			# Update depends_on and label in case they differ
			frappe.db.set_value(
				"Custom Field",
				{"dt": "Customer", "fieldname": df["fieldname"]},
				{
					"label": df.get("label"),
					"depends_on": df.get("depends_on", ""),
				},
			)
		else:
			df["dt"] = "Customer"
			frappe.get_doc({"doctype": "Custom Field", **df}).insert()

	frappe.db.commit()
	frappe.clear_cache(doctype="Customer")
