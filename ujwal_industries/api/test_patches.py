# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Test API to verify custom_batchsize monkey patches are applied
"""

import frappe
from frappe import _


@frappe.whitelist()
def check_patches_status():
	"""
	Check if custom_batchsize monkey patches are applied correctly.

	Returns:
		dict: Status of patches and module information
	"""
	from erpnext.manufacturing.doctype.bom.bom import BOM
	from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder

	status = {
		"bom_update_cost_module": BOM.update_cost.__module__,
		"bom_has_custom_method": hasattr(BOM, 'calculate_op_cost_per_unit_with_custom_batchsize'),
		"bom_validate_operations_module": BOM.validate_operations.__module__,
		"workorder_set_operations_module": WorkOrder.set_work_order_operations.__module__,
		"workorder_update_status_module": WorkOrder.update_operation_status.__module__,
	}

	# Check if patches are applied
	patches_applied = (
		"ujwal" in status["bom_update_cost_module"] or
		"ujwal" in status["workorder_set_operations_module"]
	)

	status["patches_applied"] = patches_applied
	status["status"] = "✅ Patches Active" if patches_applied else "⚠️ Patches Not Applied"

	return status
