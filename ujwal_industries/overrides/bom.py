# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
BOM Overrides

Monkey-patches ERPNext BOM functions to use custom_batchsize instead of batch_size.
This ensures operation costing calculations use the custom batch size field.
"""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils import cint
import json


def update_bom_update_cost(self, update_parent=True, from_child_bom=False, update_hour_rate=True, save=True):
	"""
	Monkey-patch for BOM.update_cost() to use custom_batchsize in operation cost calculations.

	Calculates operating costs and uses custom_batchsize for per-unit cost division.
	"""
	# Import here to avoid circular imports
	from erpnext.manufacturing.doctype.bom.bom import get_bom_items_as_dict

	if self.docstatus == 2:
		return

	# Get items from child BOMs
	existing_bom_cost = self.total_cost
	if self.items:
		self.child_bom_cost = sum(
			flt(d.amount) for d in self.items if d.bom_no and d.bom_no != self.name
		)

	# Calculate operation costs with custom_batchsize
	if self.operations:
		self.calculate_op_cost(update_hour_rate)
		self.calculate_op_cost_per_unit_with_custom_batchsize()

	# Update material costs
	if self.items:
		self.calculate_rm_cost(save=save)

	# Calculate scrap material
	if self.scrap_items:
		self.total_scrap_cost = sum(flt(d.amount) for d in self.scrap_items)

	# Update total cost
	# Avi
	# self.calculate_total()
	self.calculate_cost()
	# Avi

	# Update parent BOM if needed
	if save:
		self.save()

	if update_parent and self.parent_bom:
		parent_bom = frappe.get_doc("BOM", self.parent_bom)
		parent_bom.update_cost(from_child_bom=True, update_hour_rate=update_hour_rate, save=save)


def calculate_op_cost_per_unit_with_custom_batchsize(self):
	"""
	Calculate operation cost per unit using custom_batchsize.

	For each operation row:
	- cost_per_unit = operating_cost / custom_batchsize
	- base_cost_per_unit = base_operating_cost / custom_batchsize
	"""
	for row in self.operations:
		# Use custom_batchsize if available, otherwise fallback to batch_size, then default to 1
		batch_size = flt(row.get("custom_batchsize") or row.get("batch_size") or 1.0)

		# Ensure batch_size is not zero
		if batch_size <= 0:
			batch_size = 1.0

		# Calculate per-unit costs
		row.cost_per_unit = flt(row.operating_cost) / batch_size
		row.base_cost_per_unit = flt(row.base_operating_cost) / batch_size


def update_bom_validate_operations(self):
	"""
	Monkey-patch for BOM.validate_operations() to validate custom_batchsize.

	Ensures custom_batchsize is set and defaults to 1 if missing or invalid.
	"""
	if not self.operations:
		return

	for row in self.operations:
		# Validate custom_batchsize exists and is positive
		if not row.get("custom_batchsize") or flt(row.custom_batchsize) <= 0:
			row.custom_batchsize = 1

		# Also update batch_size for backward compatibility (if field exists)
		if "batch_size" in row.as_dict():
			row.batch_size = row.custom_batchsize


def apply_bom_overrides():
	"""
	Apply monkey patches to BOM class methods.

	This function should be called from hooks.py during app initialization.
	"""
	# Import BOM class
	try:
		from erpnext.manufacturing.doctype.bom.bom import BOM

		# Monkey-patch BOM methods
		BOM.update_cost = update_bom_update_cost
		BOM.calculate_op_cost_per_unit_with_custom_batchsize = calculate_op_cost_per_unit_with_custom_batchsize
		BOM.validate_operations = update_bom_validate_operations

		# Also hook into the calculate_op_cost to use our custom function
		original_calculate_op_cost = BOM.calculate_op_cost

		def patched_calculate_op_cost(self, update_hour_rate=False):
			# Call original
			original_calculate_op_cost(self, update_hour_rate)
			# Then apply custom_batchsize per-unit calculation
			self.calculate_op_cost_per_unit_with_custom_batchsize()

		BOM.calculate_op_cost = patched_calculate_op_cost

	except ImportError:
		frappe.log_error("Failed to import BOM for monkey patching", "BOM Override Error")


def on_update_validate_default_tool(doc, method):
    operation_default_map = {}

    for row in doc.custom_tool_details:
        if row.is_default:
            if row.operation in operation_default_map:
                frappe.throw(
                    _("For Operation <b>{0}</b>, only one Tool can be marked as Default.")
                    .format(row.operation)
                )
            operation_default_map[row.operation] = row.tool
            
            
def validate_default_tool(doc, method):
    operation_default_map = {}

    for row in doc.custom_tool_details:
        if row.is_default:
            if row.operation in operation_default_map:
                frappe.throw(
                    _("For Operation <b>{0}</b>, only one Tool can be marked as Default.")
                    .format(row.operation)
                )
            operation_default_map[row.operation] = row.tool
            
# import frappe
# from frappe.utils import flt


# def validate_bom(doc, method):

#     # ------------------------------
#     # Machine Count Auto Update
#     # ------------------------------
#     for op in doc.operations:

#         if op.custom_workstations_csv:
#             machines = [m.strip() for m in op.custom_workstations_csv.split(",") if m]
#             op.custom_machine_count = len(machines)
#         else:
#             op.custom_machine_count = 0

#     # ------------------------------
#     # Tool vs Lot Validation
#     # ------------------------------
#     for op in doc.operations:

#         operation_name = op.operation
#         lot_capacity = flt(op.custom_fixed_lot_capacity)

#         # find tools mapped to this operation
#         tool_rows = [
#             t for t in doc.custom_tool_details
#             if t.operation == operation_name and flt(t.tool_load_quantity) > 0
#         ]

#         # CASE 1: Both exist → block
#         if lot_capacity > 0 and tool_rows:

#             frappe.throw(
#                 f"""
#                 <b>Invalid Capacity Setup</b><br><br>
#                 Operation <b>{operation_name}</b> cannot have both:
#                 <br>• Fixed Lot Capacity
#                 <br>• Tool Load Quantity
#                 <br><br>Please remove one of them.
#                 """
#             )