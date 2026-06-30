# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
Work Order Overrides

Monkey-patches ERPNext Work Order functions to use custom_batchsize instead of batch_size.
This allows ujwal_industries to use their custom batch size field throughout manufacturing.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt


def split_qty_based_on_batch_size(work_order, row, qty):
	"""
	Override ERPNext split_qty_based_on_batch_size to use custom_batchsize.

	Original function: erpnext.manufacturing.doctype.work_order.work_order.split_qty_based_on_batch_size

	Splits job card quantity based on operation's custom_batchsize setting.
	"""
	# Get batch size (prefer custom_batchsize, fallback to batch_size)
	batch_size = flt(row.get("custom_batchsize") or row.get("batch_size") or 0)

	# Check if Operation has "create_job_card_based_on_batch_size" enabled
	if not cint(frappe.db.get_value("Operation", row.operation, "create_job_card_based_on_batch_size")):
		# Use work order qty if batch size creation is not enabled
		batch_size = row.get("qty") or getattr(work_order, "qty", 0)

	# Set job_card_qty to batch_size
	row.job_card_qty = batch_size or row.get("qty") or getattr(work_order, "qty", 0)

	# If batch_size exists and qty >= batch_size, split qty
	if batch_size and qty >= batch_size:
		qty -= batch_size
		return qty

	return qty


def update_work_order_set_work_order_operations(self):
	"""
	Monkey-patch for Work Order.set_work_order_operations() to use custom_batchsize.

	Fetches BOM operations and populates Work Order Operations with custom_batchsize.
	"""
	self.operations = []

	if not self.bom_no:
		return

	# Fetch operations from BOM Operation with custom_batchsize
	# Use COALESCE to fallback to batch_size if custom_batchsize is 0 or NULL
	operations = frappe.db.sql(
		"""
		SELECT
			operation,
			description,
			workstation,
			custom_workstations_csv,
			idx,
			base_hour_rate as hour_rate,
			time_in_mins,
			"Pending" as status,
			parent as bom,
			COALESCE(NULLIF(custom_batchsize, 0), batch_size) as batch_size,
			sequence_id,
			fixed_time
		FROM
			`tabBOM Operation`
		WHERE
			parent = %s
			AND parenttype = 'BOM'
		ORDER BY idx
		""",
		self.bom_no,
		as_dict=1,
	)

	parallel_row_counts = _get_parallel_row_counts(operations)

	# Populate operations
	for d in operations:
		d.time_in_mins = _calculate_operation_time(self.qty, d, parallel_row_counts.get(d.idx, 1))

		# Fall back to the first machine in custom_workstations_csv when the BOM
		# operation has no workstation set directly.
		workstation = d.workstation or _first_csv_workstation(d.custom_workstations_csv)

		# Append to operations table
		self.append("operations", {
			"operation": d.operation,
			"description": d.description,
			"workstation": workstation,
			"hour_rate": d.hour_rate,
			"time_in_mins": d.time_in_mins,
			"status": d.status,
			"bom": d.bom,
			"batch_size": d.batch_size,  # This will be custom_batchsize value
			"sequence_id": d.sequence_id,
			"fixed_time": d.fixed_time,
		})


def _first_csv_workstation(csv_value):
	"""
	Return the first machine listed in a custom_workstations_csv string, or None.

	The CSV may store the display form "ID-Name" (e.g. "UI/MC/13-2nd Bending"),
	so resolve it to a valid Workstation name when possible.
	"""
	if not csv_value:
		return None

	first = next((ws.strip() for ws in csv_value.split(",") if ws.strip()), None)
	if not first:
		return None

	if frappe.db.exists("Workstation", first):
		return first

	if "-" in first:
		candidate = first.split("-", 1)[0].strip()
		if frappe.db.exists("Workstation", candidate):
			return candidate

	return first


def _get_parallel_row_counts(operations):
	"""
	Count consecutive BOM operation rows that represent the same logical operation
	spread across multiple workstations.
	"""
	parallel_row_counts = {}
	group = []
	previous_key = None

	for operation in operations:
		current_key = (
			operation.get("bom"),
			operation.get("operation"),
			operation.get("sequence_id") or 0,
		)

		if previous_key is not None and current_key != previous_key:
			group_size = len(group) or 1
			for row in group:
				parallel_row_counts[row.idx] = group_size
			group = []

		group.append(operation)
		previous_key = current_key

	if group:
		group_size = len(group)
		for row in group:
			parallel_row_counts[row.idx] = group_size

	return parallel_row_counts


def _calculate_operation_time(work_order_qty, operation, parallel_row_count):
	"""
	Distribute variable operation time across parallel machine rows.
	"""
	time_in_mins = flt(operation.get("time_in_mins"))

	if operation.get("fixed_time"):
		return time_in_mins

	parallel_row_count = max(cint(parallel_row_count), 1)
	qty_per_parallel_row = flt(work_order_qty) / parallel_row_count
	batch_size = flt(operation.get("batch_size") or 0)

	if batch_size > 0:
		return time_in_mins * (qty_per_parallel_row / batch_size)

	return time_in_mins * qty_per_parallel_row


def update_work_order_update_operation_status(self):
	"""
	Monkey-patch for Work Order.update_operation_status() to use custom_batchsize.

	Updates operation status and uses custom_batchsize for calculations.
	"""
	# Import here to avoid circular imports
	from erpnext.manufacturing.doctype.work_order.work_order import get_job_card

	for d in self.operations:
		# Use custom_batchsize if available, otherwise use qty
		operation_batch_size = flt(d.get("custom_batchsize") or d.get("batch_size") or self.qty)

		# Get job cards for this operation
		precision = d.precision("completed_qty")

		if not d.completed_qty:
			job_cards = get_job_card(self.name, d.operation)
			if job_cards:
				d.status = "Work in Progress"
				d.completed_qty = 0
				for job_card in job_cards:
					if job_card.status == "Completed":
						d.completed_qty += job_card.total_completed_qty

				d.completed_qty = flt(d.completed_qty, precision)

				if d.completed_qty >= operation_batch_size:
					d.status = "Completed"


def apply_work_order_overrides():
	"""
	Apply monkey patches to Work Order class methods.

	This function should be called from hooks.py during app initialization.
	"""
	from erpnext.manufacturing.doctype.work_order import work_order
	from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder

	# Monkey-patch the standalone split function
	work_order.split_qty_based_on_batch_size = split_qty_based_on_batch_size

	# Monkey-patch Work Order class methods
	WorkOrder.set_work_order_operations = update_work_order_set_work_order_operations
	WorkOrder.update_operation_status = update_work_order_update_operation_status
