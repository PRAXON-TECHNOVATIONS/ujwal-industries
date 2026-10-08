import frappe


def execute():
	settings = frappe.get_single("Ujwal Industries Setting")
	if settings.get("po_visibility_rules"):
		return

	settings.append("po_visibility_rules", {"role": "Sales & Purchase Head", "show_normal": 1})
	settings.append("po_visibility_rules", {"role": "Outsource Store Manager", "show_subcontracted": 1})
	settings.save(ignore_permissions=True)
