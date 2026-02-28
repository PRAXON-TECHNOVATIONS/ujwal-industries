# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe
from frappe import _, msgprint
from frappe.model.document import Document
from frappe.utils import getdate, get_datetime, add_to_date, add_days, now_datetime, flt, cint
from typing import Any
import math
from datetime import datetime, timedelta

# Import helper functions from production_plan overrides
from ujwal_industries.ujwal_industries.overrides.pp_utils import (
	_get_allow_backdated_setting,
	_calculate_production_minutes,
	_to_datetime,
	_subtract_minutes_from_datetime,
	get_subcontract_lead_time,
	get_supplier_lead_time,
	_backward_schedule,
	_get_effective_shift_config,
	_current_shift_datetime,
	shift_aware_forward_schedule,
	_as_timedelta,
	_get_holiday_set,
	_prev_working_date,
	get_holiday_adjusted_date,
)


def get_default_supplier_for_item(item_code: str, company: str) -> str | None:
	"""
	Get default supplier for an item from Item Subcontracting Supplier table

	Args:
		item_code: Item code
		company: Company name

	Returns:
		Default supplier name or None
	"""
	result = frappe.db.get_value(
		"Item Subcontracting Supplier",
		{
			"parent": item_code,
			"company": company,
			"is_default": 1
		},
		"supplier"
	)
	return result


class BulkPreProductionPlan(Document):
	def validate(self):
		"""Validate the document before save"""
		# Validate delivery date range for bulk SO workflow
		if self.from_delivery_date and self.to_delivery_date:
			if getdate(self.from_delivery_date) > getdate(self.to_delivery_date):
				frappe.throw(_("From Delivery Date cannot be greater than To Delivery Date"))

		# Calculate total planned qty
		self.calculate_total_planned_qty()

		# Set status
		self.set_status()

	def calculate_total_planned_qty(self):
		"""Calculate total planned quantity from po_items"""
		self.total_planned_qty = 0
		self.total_produced_qty = 0

		for d in self.po_items:
			self.total_planned_qty += flt(d.planned_qty)
			self.total_produced_qty += flt(d.produced_qty)

	def set_status(self):
		"""Set document status based on production progress"""
		if self.docstatus == 0:
			self.status = "Draft"
		elif self.docstatus == 1:
			if self.total_produced_qty == 0:
				self.status = "Not Started"
			elif self.total_produced_qty < self.total_planned_qty:
				self.status = "In Process"
			elif self.total_produced_qty >= self.total_planned_qty:
				self.status = "Completed"
		elif self.docstatus == 2:
			self.status = "Cancelled"

	def on_submit(self):
		"""Create Production Plans asynchronously on submit - one per sales order"""
		if not self.sales_orders:
			return

		# Enqueue async job to create production plans
		frappe.enqueue(
			"ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.create_production_plans_async",
			bulk_pp_name=self.name,
			timeout=3000,
			queue="long"
		)

		frappe.msgprint(
			_("Production Plans are being created in the background. You will be notified once complete."),
			indicator="blue",
			alert=True
		)

	@frappe.whitelist()
	def get_items(self):
		"""
		Get items from Sales Orders or Material Requests (Production Plan workflow)
		"""
		self.set("po_items", [])

		if self.get_items_from == "Sales Order":
			self.get_so_items()
		elif self.get_items_from == "Material Request":
			self.get_mr_items()

	def get_so_items(self):
		"""
		Get items from Sales Orders (Production Plan style)
		Uses ERPNext's standard Production Plan logic
		"""
		if not self.get("sales_orders"):
			frappe.throw(_("Please fill the Sales Orders table"), title=_("Sales Orders Required"))

		so_list = [d.sales_order for d in self.sales_orders if d.sales_order]

		if not so_list:
			frappe.throw(_("Please add Sales Orders"))

		# Use ERPNext's standard query logic
		items = frappe.db.sql("""
			SELECT
				soi.parent as parent,
				soi.item_code,
				soi.warehouse,
				soi.qty,
				soi.work_order_qty,
				soi.delivered_qty,
				soi.conversion_factor,
				soi.description,
				soi.name as sales_order_item,
				soi.bom_no
			FROM
				`tabSales Order Item` soi
			WHERE
				soi.parent IN %(so_list)s
				AND soi.docstatus = 1
				AND soi.qty > soi.work_order_qty
				AND EXISTS (
					SELECT 1 FROM `tabBOM` bom
					WHERE bom.item = soi.item_code
					AND bom.is_active = 1
					AND bom.docstatus = 1
				)
		""", {'so_list': so_list}, as_dict=True)

		for item in items:
			item.pending_qty = (flt(item.qty) - flt(item.work_order_qty)) * flt(item.conversion_factor)

		self.add_items(items)
		self.calculate_total_planned_qty()

	def get_mr_items(self):
		"""
		Get items from Material Requests (Production Plan style)
		"""
		if not self.get("material_requests"):
			frappe.throw(_("Please fill the Material Requests table"), title=_("Material Requests Required"))

		mr_list = [d.material_request for d in self.material_requests if d.material_request]

		if not mr_list:
			frappe.throw(_("Please add Material Requests"))

		items = frappe.db.sql("""
			SELECT
				mri.parent as parent,
				mri.name,
				mri.item_code,
				mri.warehouse,
				mri.description,
				mri.bom_no,
				(mri.qty - mri.ordered_qty) * mri.conversion_factor as pending_qty
			FROM
				`tabMaterial Request Item` mri
			WHERE
				mri.parent IN %(mr_list)s
				AND mri.docstatus = 1
				AND mri.qty > mri.ordered_qty
				AND EXISTS (
					SELECT 1 FROM `tabBOM` bom
					WHERE bom.item = mri.item_code
					AND bom.is_active = 1
					AND bom.docstatus = 1
				)
		""", {'mr_list': mr_list}, as_dict=True)

		self.add_items(items)
		self.calculate_total_planned_qty()

	def add_items(self, items):
		"""
		Add items to po_items table
		Supports both combine_items and non-combined modes
		"""
		refs = {}

		for data in items:
			if not data.pending_qty:
				continue

			# Get BOM
			bom_no = data.get("bom_no") or frappe.db.get_value("BOM", {
				"item": data.item_code,
				"is_active": 1,
				"is_default": 1
			}, "name")

			if not bom_no:
				continue

			# Get item details
			item_doc = frappe.get_doc("Item", data.item_code)

			if self.combine_items:
				# Combine mode: aggregate by BOM
				if bom_no in refs:
					refs[bom_no]["qty"] += data.pending_qty
					continue
				else:
					refs[bom_no] = {
						"qty": data.pending_qty,
						"item_code": data.item_code,
						"warehouse": data.warehouse,
						"description": data.description,
						"bom_no": bom_no,
						"stock_uom": item_doc.stock_uom,
						"sales_order": data.get("parent"),
						"sales_order_item": data.get("sales_order_item") or data.get("name")
					}
			else:
				# Non-combine mode: add each item separately
				self.append("po_items", {
					"item_code": data.item_code,
					"bom_no": bom_no,
					"planned_qty": data.pending_qty,
					"stock_uom": item_doc.stock_uom,
					"warehouse": data.warehouse,
					"description": data.description,
					"planned_start_date": now_datetime(),
					"sales_order": data.get("parent"),
					"sales_order_item": data.get("sales_order_item") or data.get("name"),
					"material_request": data.get("parent") if self.get_items_from == "Material Request" else None,
					"material_request_item": data.get("name") if self.get_items_from == "Material Request" else None
				})

		# Add combined items
		if self.combine_items:
			for bom_no, item_data in refs.items():
				self.append("po_items", {
					"item_code": item_data["item_code"],
					"bom_no": bom_no,
					"planned_qty": item_data["qty"],
					"stock_uom": item_data["stock_uom"],
					"warehouse": item_data["warehouse"],
					"description": item_data["description"],
					"planned_start_date": now_datetime(),
					"sales_order": item_data.get("sales_order"),
					"sales_order_item": item_data.get("sales_order_item")
				})

	@frappe.whitelist()
	def get_sub_assembly_items(self):
		"""
		Get sub assembly items from BOMs of po_items
		Production Plan compatible method
		"""
		if not self.po_items:
			frappe.throw(_("Please add items in the Finished Goods table first"))

		self.sub_assembly_items = []

		for item in self.po_items:
			if not item.bom_no:
				continue

			# Get sub assemblies using ERPNext logic
			self.get_sub_assembly_items_from_bom(item, item.bom_no, item.planned_qty, item.item_code)

	def get_sub_assembly_items_from_bom(self, fg_item_row, bom_no, qty, parent_item, level=0):
		"""
		Recursively get sub assembly items from BOM
		Compatible with Production Plan logic
		"""
		bom_items = frappe.db.sql("""
			SELECT
				bi.item_code,
				bi.qty as qty_per_unit,
				bi.stock_uom,
				i.is_sub_contracted_item,
				i.default_bom,
				i.item_name
			FROM
				`tabBOM Item` bi
			INNER JOIN
				`tabItem` i ON bi.item_code = i.name
			WHERE
				bi.parent = %s
			ORDER BY
				bi.idx
		""", bom_no, as_dict=True)

		for bom_item in bom_items:
			if bom_item.default_bom:
				# This is a sub assembly
				required_qty = bom_item.qty_per_unit * qty

				self.append("sub_assembly_items", {
					"production_item": bom_item.item_code,
					"item_name": bom_item.item_name,
					"parent_item_code": parent_item,
					"qty": required_qty,
					"bom_no": bom_item.default_bom,
					"bom_level": level,
					"stock_uom": bom_item.stock_uom,
					"type_of_manufacturing": "Subcontract" if bom_item.is_sub_contracted_item else "In House",
					"fg_warehouse": fg_item_row.warehouse,
					"schedule_date": fg_item_row.planned_start_date,
					"sales_order": fg_item_row.sales_order
				})

				# Recurse into child BOM
				self.get_sub_assembly_items_from_bom(
					fg_item_row, bom_item.default_bom, required_qty, bom_item.item_code, level + 1
				)

	@frappe.whitelist()
	def get_items_for_mr(self):
		"""
		Get raw materials for Material Request Planning
		Production Plan compatible method
		"""
		if not self.po_items:
			frappe.throw(_("Please add items to manufacture first"))

		self.mr_items = []

		for item in self.po_items:
			if not item.bom_no:
				continue

			# Get all materials from BOM including sub-assemblies
			self.get_raw_materials_from_bom(item, item.bom_no, item.planned_qty)

	def get_raw_materials_from_bom(self, fg_item_row, bom_no, qty):
		"""
		Get all raw materials from BOM recursively
		"""
		bom_items = frappe.db.sql("""
			SELECT
				bi.item_code,
				bi.qty as qty_per_unit,
				bi.stock_uom,
				i.default_bom
			FROM
				`tabBOM Item` bi
			INNER JOIN
				`tabItem` i ON bi.item_code = i.name
			WHERE
				bi.parent = %s
		""", bom_no, as_dict=True)

		for bom_item in bom_items:
			required_qty = bom_item.qty_per_unit * qty

			if bom_item.default_bom:
				# Recurse into sub-assembly
				self.get_raw_materials_from_bom(fg_item_row, bom_item.default_bom, required_qty)
			else:
				# This is a raw material
				# Check if already exists and combine
				existing = None
				for mr_item in self.mr_items:
					if mr_item.item_code == bom_item.item_code and mr_item.warehouse == self.for_warehouse:
						existing = mr_item
						break

				if existing:
					existing.quantity += required_qty
					existing.required_bom_qty += required_qty
				else:
					self.append("mr_items", {
						"item_code": bom_item.item_code,
						"warehouse": self.for_warehouse or fg_item_row.warehouse,
						"quantity": required_qty,
						"required_bom_qty": required_qty,
						"uom": bom_item.stock_uom,
						"schedule_date": fg_item_row.planned_start_date,
						"material_request_type": "Purchase",
						"sales_order": fg_item_row.sales_order
					})


# ============================================================================
# BULK SALES ORDER WORKFLOW METHODS (Original Bulk PP functionality)
# ============================================================================

@frappe.whitelist()
def get_sales_orders(from_delivery_date: str, to_delivery_date: str, company: str) -> dict[str, Any]:
	"""
	Fetch Sales Orders based on delivery_date range (Bulk PP workflow)

	Args:
		from_delivery_date: Start date of delivery range
		to_delivery_date: End date of delivery range
		company: Company name

	Returns:
		Dict with sales_orders list
	"""
	if not from_delivery_date or not to_delivery_date:
		frappe.throw(_("Please set From Delivery Date and To Delivery Date"))

	if not company:
		frappe.throw(_("Please set Company"))

	# Fetch Sales Orders with delivery_date in range
	sales_orders = frappe.db.sql("""
		SELECT
			so.name as sales_order,
			so.customer,
			so.delivery_date,
			so.grand_total,
			so.status
		FROM
			`tabSales Order` so
		WHERE
			so.docstatus = 1
			AND so.status NOT IN ('Closed', 'Cancelled', 'Completed')
			AND so.delivery_date BETWEEN %(from_date)s AND %(to_date)s
			AND so.company = %(company)s
		ORDER BY
			so.delivery_date ASC
	""", {
		'from_date': from_delivery_date,
		'to_date': to_delivery_date,
		'company': company
	}, as_dict=True)

	# Just return the sales_orders data - don't save to avoid naming series issues
	# The frontend will populate the child table

	frappe.msgprint(_("Found {0} Sales Orders in the date range").format(len(sales_orders)))

	# Return formatted data for frontend to populate
	return {
		'sales_orders': [
			{
				'sales_order': so.sales_order,
				'customer': so.customer,
				'delivery_date': so.delivery_date,
				'grand_total': so.grand_total,
				'status': so.status,
				'is_selected': 1,
				'for_warehouse': '',
				'items_generated': 0
			}
			for so in sales_orders
		]
	}

@frappe.whitelist()
def get_tool_days(bom):
    bom_doc = frappe.get_doc("BOM", bom)
    tool_min = 0
    if bom_doc.custom_tool_details:
        for i in bom_doc.custom_tool_details:
            if i.is_default:
                tool = frappe.get_doc("Asset",i.tool)
                tool_min += tool.custom_required_maintenance_days * 1440
                
    return tool_min
 

@frappe.whitelist()
def generate_production_plan_items(docname: str) -> dict[str, Any]:
	"""
	Generate Production Plan items for selected Sales Orders (Bulk PP workflow)

	Args:
		docname: Bulk Pre Production Plan name

	Returns:
		Dict with generated items count
	"""
	doc = frappe.get_doc("Bulk Pre Production Plan", docname)

	if not doc.sales_orders:
		frappe.throw(_("No Sales Orders found. Please fetch Sales Orders first."))

	# Get selected sales orders
	selected_sos = [row.sales_order for row in doc.sales_orders if row.is_selected]

	if not selected_sos:
		frappe.throw(_("Please select at least one Sales Order"))

	# Clear existing items
	doc.po_items = []
	doc.sub_assembly_items = []
	doc.mr_items = []

	total_po_items = 0
	total_sfg_items = 0
	total_mr_items = 0

	# Process each selected Sales Order
	for so_name in selected_sos:
		# Generate items for this SO
		result = generate_items_for_sales_order(doc, so_name)

		total_po_items += result['po_items']
		total_sfg_items += result['sfg_items']
		total_mr_items += result['mr_items']

		# Mark as generated
		for so_row in doc.sales_orders:
			if so_row.sales_order == so_name:
				so_row.items_generated = 1
				break

	# Run the same date validation as Production Plan — checks allow_backdated setting
	# and throws/adjusts if any planned dates fall in the past.
	from ujwal_industries.ujwal_industries.overrides.pp_fg_dates import validate_planned_start_dates
	validate_planned_start_dates(doc)

	# The warehouse field is conditional (get_items_from == "Material Request") but
	# Frappe may still enforce it server-side in the bulk SO workflow.
	doc.flags.ignore_mandatory = True
	doc.save()
	doc.flags.ignore_mandatory = False

	frappe.msgprint(_("""
		Generated:
		- {0} FG Items
		- {1} Sub Assembly Items
		- {2} Raw Material Items
	""").format(total_po_items, total_sfg_items, total_mr_items))

	return {
		'po_items': total_po_items,
		'sfg_items': total_sfg_items,
		'mr_items': total_mr_items
	}


def generate_items_for_sales_order(doc: Document, so_name: str) -> dict[str, int]:
	"""
	Generate production plan items for a single Sales Order (Bulk PP workflow)

	Args:
		doc: Bulk Pre Production Plan document
		so_name: Sales Order name

	Returns:
		Dict with counts of generated items
	"""
	# Get the warehouse for this sales order from sales_orders table
	so_warehouse = None
	for so_row in doc.sales_orders:
		if so_row.sales_order == so_name:
			so_warehouse = so_row.for_warehouse
			break

	# Get Sales Order items
	so_items = frappe.db.sql("""
		SELECT
			soi.item_code,
			soi.qty,
			soi.stock_uom,
			soi.warehouse,
			soi.delivery_date,
			so.delivery_date as so_delivery_date,
			i.is_sub_contracted_item
		FROM
			`tabSales Order Item` soi
		INNER JOIN
			`tabSales Order` so ON soi.parent = so.name
		INNER JOIN
			`tabItem` i ON soi.item_code = i.name
		WHERE
			soi.parent = %(so_name)s
			AND soi.docstatus = 1
	""", {'so_name': so_name}, as_dict=True)

	po_count = 0
	sfg_count = 0
	mr_count = 0

	# Process each SO item
	for item in so_items:
		# Get default BOM for item
		bom = frappe.db.get_value("BOM", {
			"item": item.item_code,
			"is_active": 1,
			"is_default": 1
		}, "name")

		if not bom:
			continue

		# Add to po_items (FG items)
		delivery_date = item.delivery_date or item.so_delivery_date

		# Determine manufacturing type - FG items default to In House
		manufacturing_type = 'In House'

		# Get warehouse - use item warehouse or fall back to company default
		warehouse = item.warehouse
		if not warehouse:
			warehouse = frappe.db.get_value("Company", doc.company, "default_warehouse")

		doc.append('po_items', {
			'sales_order': so_name,
			'item_code': item.item_code,
			'bom_no': bom,
			'planned_qty': item.qty,
			'stock_uom': item.stock_uom,
			'warehouse': warehouse,
			'planned_start_date': delivery_date,
			'manufacturing_type': manufacturing_type
		})
		po_count += 1

		# Get sub assembly items from BOM
		sfg_result = get_sub_assembly_items_from_bom(
			doc, so_name, item.item_code, bom, item.qty, delivery_date,
			level=0, fg_qty=None, parent_item=item.item_code, rm_warehouse=so_warehouse
		)
		sfg_count += sfg_result['sfg_count']
		mr_count += sfg_result['mr_count']

	# ── Set each MR item's warehouse from Item Default (per-item, per-company) ─
	# Must happen BEFORE bin stock check so each item is checked against its
	# own warehouse (not the SO's FG warehouse which may have unrelated stock).
	_apply_item_default_warehouses(doc, so_name)

	# ── Warehouse stock check (same logic as standard Production Plan) ──────
	# Checks each item's own warehouse. Items fully covered by available stock
	# are removed; partially covered get reduced qty.
	_apply_bin_stock_check(doc, so_name)

	# Recalculate mr_count after stock-check removals
	mr_count = sum(1 for r in doc.mr_items if r.sales_order == so_name)

	# Calculate dates for all items
	calculate_dates_for_sales_order(doc, so_name)

	return {
		'po_items': po_count,
		'sfg_items': sfg_count,
		'mr_items': mr_count
	}


def get_sub_assembly_items_from_bom(
	doc: Document,
	so_name: str,
	fg_item: str,
	bom: str,
	qty: float,
	delivery_date: str,
	level: int = 0,
	fg_qty: float = None,
	parent_item: str = None,
	rm_warehouse: str = None
) -> dict[str, int]:
	"""
	Recursively get sub assembly items and raw materials from BOM
	Uses FG qty for all SFG levels (Production Plan logic)

	Args:
		doc: Bulk Pre Production Plan document
		so_name: Sales Order name
		fg_item: Finished Good item code
		bom: BOM name
		qty: Required quantity
		delivery_date: Delivery date
		level: BOM level
		fg_qty: Original FG quantity
		parent_item: Immediate parent item code
		rm_warehouse: Raw materials warehouse for this SO

	Returns:
		Dict with sfg_count and mr_count
	"""
	sfg_count = 0
	mr_count = 0

	if fg_qty is None:
		fg_qty = qty

	# Get BOM items — qty_per_unit = stock_qty / bom.quantity (ERPNext standard)
	# Uses bi.bom_no (tabBOM Item) to classify sub-assembly vs raw material,
	# matching ERPNext's get_bom_children / get_sub_assembly_items logic.
	bom_items = frappe.db.sql("""
		SELECT
			bi.item_code,
			bi.stock_qty / NULLIF(b.quantity, 0) as qty_per_unit,
			bi.stock_uom,
			bi.bom_no as item_bom_no,
			i.is_sub_contracted_item
		FROM
			`tabBOM Item` bi
		INNER JOIN
			`tabItem` i ON bi.item_code = i.name
		INNER JOIN
			`tabBOM` b ON b.name = bi.parent
		WHERE
			bi.parent = %(bom)s
		ORDER BY
			bi.idx
	""", {'bom': bom}, as_dict=True)

	for bom_item in bom_items:
		required_qty = bom_item.qty_per_unit * qty

		if bom_item.item_bom_no:
			# Sub assembly item — use actual required_qty (qty_per_unit × parent qty)
			doc.append('sub_assembly_items', {
				'sales_order': so_name,
				'fg_item_code': fg_item,
				'production_item': bom_item.item_code,
				'parent_item_code': parent_item,
				'bom_no': bom_item.item_bom_no,
				'bom_level': level,
				'qty': required_qty,
				'stock_uom': bom_item.stock_uom,
				'schedule_date': delivery_date,
				'type_of_manufacturing': 'Subcontract' if bom_item.is_sub_contracted_item else 'In House'
			})
			sfg_count += 1

			# Recurse with required_qty so nested MR/SFG use the correct base qty
			child_result = get_sub_assembly_items_from_bom(
				doc, so_name, fg_item, bom_item.item_bom_no,
				required_qty, delivery_date, level + 1, fg_qty, bom_item.item_code, rm_warehouse
			)
			sfg_count += child_result['sfg_count']
			mr_count += child_result['mr_count']
		else:
			# Raw material — add to MR items
			doc.append('mr_items', {
				'sales_order': so_name,
				'fg_item_code': fg_item,
				'item_code': bom_item.item_code,
				'quantity': required_qty,
				'required_bom_qty': required_qty,
				'uom': bom_item.stock_uom,
				'material_request_type': 'Purchase',
				'schedule_date': delivery_date,
				'warehouse': rm_warehouse or '',
			})
			mr_count += 1

	return {
		'sfg_count': sfg_count,
		'mr_count': mr_count
	}


def _apply_bin_stock_check(doc: "Document", so_name: str) -> None:
	"""
	Reduce MR item quantities by available stock at each item's own warehouse.

	Checks projected_qty in tabBin for each MR item at its assigned warehouse
	(set by _apply_item_default_warehouses). Items with no warehouse assigned
	are skipped. Items fully covered by stock are removed; partially covered
	get reduced qty.

	This mirrors ERPNext Production Plan's get_material_request_items logic
	but uses per-item warehouses rather than a single global warehouse, so
	we don't falsely suppress items because an unrelated warehouse has stock.
	"""
	so_mr_items = [r for r in doc.mr_items if r.sales_order == so_name]
	if not so_mr_items:
		return

	# Group items by warehouse for batch queries
	warehouse_items: dict[str, list[str]] = {}
	for mr_row in so_mr_items:
		wh = mr_row.warehouse
		if wh:
			warehouse_items.setdefault(wh, []).append(mr_row.item_code)

	if not warehouse_items:
		return

	# Batch-fetch projected_qty per (warehouse, item_code)
	projected_map: dict[tuple[str, str], float] = {}
	for wh, items in warehouse_items.items():
		bin_rows = frappe.db.sql("""
			SELECT item_code, SUM(projected_qty) AS projected_qty
			FROM `tabBin`
			WHERE item_code IN %(items)s AND warehouse = %(warehouse)s
			GROUP BY item_code
		""", {"items": items, "warehouse": wh}, as_dict=True)
		for r in bin_rows:
			projected_map[(wh, r.item_code)] = flt(r.projected_qty)

	# consumed: (warehouse, item_code) → qty already allocated to earlier rows
	consumed: dict[tuple[str, str], float] = {}
	to_remove = []

	for mr_row in so_mr_items:
		wh = mr_row.warehouse
		if not wh:
			continue  # no warehouse set → skip stock check for this item

		key = (wh, mr_row.item_code)
		projected = projected_map.get(key, 0.0)
		already_consumed = consumed.get(key, 0.0)
		available = max(0.0, projected - already_consumed)

		if available >= flt(mr_row.quantity):
			# Fully covered by stock — remove this MR row
			consumed[key] = already_consumed + flt(mr_row.quantity)
			to_remove.append(mr_row)
		elif available > 0:
			# Partially covered — reduce qty
			consumed[key] = already_consumed + available
			mr_row.quantity = flt(mr_row.quantity) - available
		# else: no stock available — keep full qty as-is

	for row in to_remove:
		doc.mr_items.remove(row)


def _apply_item_default_warehouses(doc: "Document", so_name: str) -> None:
	"""
	Set each MR item's warehouse from Item Default.default_warehouse (company-specific).

	A single batch query fetches all item defaults for the company; individual
	MR item rows are updated only when a default warehouse is found.
	MR items with no item default warehouse are left unchanged.
	"""
	so_mr_items = [r for r in doc.mr_items if r.sales_order == so_name]
	if not so_mr_items:
		return

	item_codes = list(set(r.item_code for r in so_mr_items))

	rows = frappe.db.sql("""
		SELECT parent AS item_code, default_warehouse
		FROM `tabItem Default`
		WHERE parent IN %(items)s
		  AND company = %(company)s
		  AND default_warehouse IS NOT NULL
		  AND default_warehouse != ''
	""", {"items": item_codes, "company": doc.company}, as_dict=True)

	warehouse_map: dict[str, str] = {r.item_code: r.default_warehouse for r in rows}

	for mr_row in so_mr_items:
		wh = warehouse_map.get(mr_row.item_code)
		if wh:
			mr_row.warehouse = wh


def _fetch_bom_operations_cache(bom_nos: list[str]) -> dict[str, list[dict[str, Any]]]:
	"""Batch fetch BOM operations for a list of BOMs. Returns cache for _calculate_production_minutes."""
	if not bom_nos:
		return {}

	operations_data = frappe.db.sql("""
		SELECT parent as bom_no, time_in_mins, custom_batchsize, operation, idx
		FROM `tabBOM Operation`
		WHERE parent IN %(bom_nos)s
		ORDER BY parent, idx
	""", {"bom_nos": bom_nos}, as_dict=True)

	cache: dict[str, list[dict[str, Any]]] = {}
	for op in operations_data:
		cache.setdefault(op.bom_no, []).append(op)
	return cache


def calculate_dates_for_sales_order(doc: Document, so_name: str):
	"""
	Shift-aware backward scheduling for FG, SFG, and MR items in a single SO.

	Algorithm mirrors pp_sfg_dates.set_subcontracting_suppliers:
	  - FG:  delivery_date → _backward_schedule → planned_start_date + custom_planned_end_date
	  - SFG (In House):    parent_start → _backward_schedule → schedule_date
	  - SFG (Subcontract): parent_start → grn_days (working) + lead_time (calendar) → schedule_date
	  - Backdate guard: if result < today → forward jump via _current_shift_datetime
	  - PASS 2: bottom-up cascade — child end > parent start → push parent + FG if needed
	  - MR: earliest parent SFG schedule − supplier lead_time → custom_start_date
	"""
	allow_backdated = _get_allow_backdated_setting()
	today = getdate()
	today_dt = _to_datetime(today)

	# ── Shift config (used for all scheduling) ────────────────────────────────
	shift_config = _get_effective_shift_config()
	holiday_list = shift_config.get("holiday_list")
	holidays_set = _get_holiday_set(holiday_list)
	_shift_start_raw = _as_timedelta(shift_config.get("start_time"))
	shift_start_td = _shift_start_raw if _shift_start_raw is not None else timedelta(hours=0)

	# ── STEP 1: FG planned_start_date (shift-aware backward from delivery) ────
	fg_bom_nos = list(set(
		row.bom_no for row in doc.po_items
		if row.sales_order == so_name and row.bom_no
	))
	fg_bom_cache = _fetch_bom_operations_cache(fg_bom_nos)

	for fg_row in doc.po_items:
		if fg_row.sales_order != so_name or not fg_row.bom_no:
			continue

		# planned_start_date was initialised to the SO delivery_date
		delivery_dt = get_datetime(fg_row.planned_start_date)
		prod_minutes = _calculate_production_minutes(fg_row.bom_no, flt(fg_row.planned_qty), fg_bom_cache)

		if prod_minutes > 0:
			calculated_start = _backward_schedule(delivery_dt, prod_minutes, shift_config)
			if not allow_backdated and getdate(calculated_start) < today:
				# Forward jump: start at shift-clamped now, forward-schedule end
				start_now = _current_shift_datetime(shift_config)
				fg_row.planned_start_date = str(start_now)
				fg_row.custom_planned_end_date = str(
					shift_aware_forward_schedule(start_now, prod_minutes, shift_config)
				)
			else:
				fg_row.planned_start_date = str(calculated_start)
				fg_row.custom_planned_end_date = str(
					shift_aware_forward_schedule(calculated_start, prod_minutes, shift_config)
				)
		else:
			if not allow_backdated and getdate(delivery_dt) < today:
				fg_row.planned_start_date = str(today_dt)
			else:
				fg_row.planned_start_date = str(delivery_dt)

	# ── STEP 2: SFG schedule_date (shift-aware) ───────────────────────────────
	fg_dates: dict[str, Any] = {}
	for fg_row in doc.po_items:
		if fg_row.sales_order == so_name and fg_row.item_code and fg_row.planned_start_date:
			fg_dates[fg_row.item_code] = fg_row.planned_start_date

	sfg_rows = [row for row in doc.sub_assembly_items if row.sales_order == so_name]
	if not sfg_rows:
		return

	sfg_bom_nos = list(set(row.bom_no for row in sfg_rows if row.bom_no))
	sfg_bom_cache = _fetch_bom_operations_cache(sfg_bom_nos)

	# Batch-fetch GRN processing days for Subcontract items
	subcontract_items = [r.production_item for r in sfg_rows if r.type_of_manufacturing == 'Subcontract']
	grn_days_map: dict[str, int] = {}
	if subcontract_items:
		raw_grn = frappe.db.sql(
			"SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days "
			"FROM `tabItem` WHERE name IN %(items)s",
			{"items": subcontract_items}, as_dict=True
		)
		grn_days_map = {d.name: int(d.grn_days) for d in raw_grn}

	# Sort top-down so parents are always processed before their children
	sfg_rows_sorted = sorted(sfg_rows, key=lambda r: (r.bom_level or 0))

	# item_start_map: (fg_item_code, item_code) → deadline datetime
	# Seeded with each FG's planned_start_date — that is when FG children must be ready
	item_start_map: dict[tuple[str, str], Any] = {}
	for fg_row in doc.po_items:
		if fg_row.sales_order == so_name and fg_row.item_code and fg_row.planned_start_date:
			item_start_map[("", fg_row.item_code)] = get_datetime(fg_row.planned_start_date)

	# per-row data: (fg_item_code, production_item) → data dict
	item_data: dict[tuple[str, str], dict[str, Any]] = {}

	# PASS 1 – TOP-DOWN backward schedule (mirrors set_subcontracting_suppliers)
	for sfg_row in sfg_rows_sorted:
		fg_key = getattr(sfg_row, 'fg_item_code', '') or ''
		parent_item = sfg_row.parent_item_code

		# Deadline = when this item's parent starts (per-chain lookup)
		end_date: Any = (
			item_start_map.get((fg_key, parent_item))
			or item_start_map.get(("", parent_item))
			or _current_shift_datetime(shift_config)
		)
		end_date = get_datetime(end_date)

		if sfg_row.type_of_manufacturing == 'Subcontract':
			# Auto-populate supplier if missing
			if not sfg_row.supplier:
				default_supplier = get_default_supplier_for_item(sfg_row.production_item, doc.company)
				if default_supplier:
					sfg_row.supplier = default_supplier

			lead_time = get_subcontract_lead_time(
				sfg_row.production_item, sfg_row.supplier, doc.company
			) if sfg_row.supplier else 0
			grn_days = grn_days_map.get(sfg_row.production_item, 0)

			# Backward: deadline − grn_days (working) − lead_time (calendar)
			receive_date = getdate(end_date)
			for _ in range(grn_days):
				receive_date = _prev_working_date(receive_date, holidays_set)
			sc_date = getdate(add_days(receive_date, -lead_time))
			start_date: Any = datetime.combine(sc_date, datetime.min.time()) + shift_start_td

			if not allow_backdated and getdate(start_date) < today:
				start_date = _current_shift_datetime(shift_config)
				end_raw = getdate(add_days(getdate(start_date), lead_time))
				end_adj = get_holiday_adjusted_date(end_raw, grn_days, holiday_list)
				end_date = datetime.combine(getdate(end_adj), datetime.min.time()) + shift_start_td

			item_data[(fg_key, sfg_row.production_item)] = {
				"row":          sfg_row,
				"schedule_date": start_date,
				"end_date":      end_date,
				"time_type":     "lead_time",
				"lead_time":     lead_time,
				"grn_days":      grn_days,
				"prod_mins":     0.0,
			}

		else:
			# In House — shift-aware backward schedule
			prod_mins = _calculate_production_minutes(
				sfg_row.bom_no, flt(sfg_row.qty), sfg_bom_cache
			) if sfg_row.bom_no else 0.0

			if prod_mins > 0:
				start_date = _backward_schedule(end_date, prod_mins, shift_config)
				if not allow_backdated and getdate(start_date) < today:
					start_date = _current_shift_datetime(shift_config)
					end_date = shift_aware_forward_schedule(start_date, prod_mins, shift_config)
			else:
				start_date = end_date

			item_data[(fg_key, sfg_row.production_item)] = {
				"row":          sfg_row,
				"schedule_date": start_date,
				"end_date":      end_date,
				"time_type":     "production_minutes",
				"lead_time":     0,
				"grn_days":      0,
				"prod_mins":     prod_mins,
			}

		# Record start for children to use as their deadline
		item_start_map[(fg_key, sfg_row.production_item)] = start_date

	# PASS 2 – BOTTOM-UP CASCADE (child end > parent start → push parent; or FG)
	# FG po_item map keyed by item_code for cascade push
	fg_po_items_map: dict[str, list] = {}
	for po_item in doc.po_items:
		if po_item.sales_order == so_name and po_item.item_code:
			fg_po_items_map.setdefault(po_item.item_code, []).append(po_item)

	fg_bom_cache_for_cascade = _fetch_bom_operations_cache(fg_bom_nos)

	sfg_rows_bottom_up = sorted(sfg_rows, key=lambda r: -(r.bom_level or 0))

	for _iter in range(20):
		any_change = False
		for sfg_row in sfg_rows_bottom_up:
			fg_key = getattr(sfg_row, 'fg_item_code', '') or ''
			data = item_data.get((fg_key, sfg_row.production_item))
			if not data:
				continue

			parent_item = sfg_row.parent_item_code
			this_end = data["end_date"]

			# ── Case A: parent is an FG ─────────────────────────────────────
			if parent_item in fg_po_items_map:
				for po_item in fg_po_items_map[parent_item]:
					fg_start = get_datetime(po_item.planned_start_date)
					if getdate(this_end) > getdate(fg_start):
						po_item.planned_start_date = str(this_end)
						item_start_map[("", po_item.item_code)] = get_datetime(this_end)
						fg_prod_mins = _calculate_production_minutes(
							po_item.bom_no, flt(po_item.planned_qty), fg_bom_cache_for_cascade
						)
						if fg_prod_mins > 0:
							po_item.custom_planned_end_date = str(
								shift_aware_forward_schedule(this_end, fg_prod_mins, shift_config)
							)
						any_change = True
				continue

			# ── Case B: parent is another SFG ──────────────────────────────
			parent_data = item_data.get((fg_key, parent_item))
			if not parent_data:
				continue

			if getdate(this_end) > getdate(parent_data["schedule_date"]):
				parent_data["schedule_date"] = this_end
				item_start_map[(fg_key, parent_item)] = this_end

				if parent_data["time_type"] == "lead_time":
					lt = parent_data["lead_time"]
					grn = parent_data["grn_days"]
					end_raw = getdate(add_days(getdate(this_end), lt))
					end_adj = get_holiday_adjusted_date(end_raw, grn, holiday_list)
					parent_data["end_date"] = (
						datetime.combine(getdate(end_adj), datetime.min.time()) + shift_start_td
					)
				else:
					parent_data["end_date"] = shift_aware_forward_schedule(
						this_end, parent_data["prod_mins"], shift_config
					)
				any_change = True

		if not any_change:
			break

	# PASS 3 – Apply final SFG dates to rows
	for data in item_data.values():
		data["row"].schedule_date = data["schedule_date"]
		data["row"].custom_schedule_end_date = data["end_date"]

	# ── STEP 3: MR dates ──────────────────────────────────────────────
	# Batch: which BOMs use which raw materials (avoids N+1 queries)
	sfg_bom_list = list(set(row.bom_no for row in sfg_rows if row.bom_no))
	mr_item_codes = list(set(row.item_code for row in doc.mr_items if row.sales_order == so_name))
	bom_item_links: dict[str, set[str]] = {}  # bom_no -> set of rm item_codes

	# Batch-fetch GRN processing days for all MR items (one query)
	mr_grn_days_map: dict[str, int] = {}
	if mr_item_codes:
		grn_raw = frappe.db.sql("""
			SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days
			FROM `tabItem` WHERE name IN %(items)s
		""", {"items": mr_item_codes}, as_dict=True)
		mr_grn_days_map = {d.name: int(d.grn_days) for d in grn_raw}

	if sfg_bom_list and mr_item_codes:
		links = frappe.db.sql("""
			SELECT parent as bom_no, item_code
			FROM `tabBOM Item`
			WHERE parent IN %(boms)s AND item_code IN %(items)s
		""", {"boms": sfg_bom_list, "items": mr_item_codes}, as_dict=True)
		for link in links:
			bom_item_links.setdefault(link.bom_no, set()).add(link.item_code)

	for mr_row in doc.mr_items:
		if mr_row.sales_order != so_name:
			continue

		# Find earliest parent SFG schedule that uses this RM
		earliest_sfg_schedule = None
		for sfg_row in sfg_rows:
			if sfg_row.bom_no and mr_row.item_code in bom_item_links.get(sfg_row.bom_no, set()):
				if sfg_row.schedule_date:
					sfg_dt = get_datetime(sfg_row.schedule_date)
					if earliest_sfg_schedule is None or sfg_dt < earliest_sfg_schedule:
						earliest_sfg_schedule = sfg_dt

		if not earliest_sfg_schedule:
			# Fall back to FG planned_start_date
			for fg_row in doc.po_items:
				if fg_row.sales_order == so_name and fg_row.planned_start_date:
					earliest_sfg_schedule = get_datetime(fg_row.planned_start_date)
					break

		if not earliest_sfg_schedule:
			continue

		# Populate supplier
		if not mr_row.custom_supplier:
			default_supplier = get_default_supplier_for_item(mr_row.item_code, doc.company)
			if default_supplier:
				mr_row.custom_supplier = default_supplier

		# Get supplier lead time + GRN processing days
		lead_time_days = 0
		if mr_row.custom_supplier:
			lt_result = get_supplier_lead_time(mr_row.item_code, mr_row.custom_supplier, doc.company)
			lead_time_days = lt_result.get("lead_time_days", 0)
		grn_days_mr = mr_grn_days_map.get(mr_row.item_code, 0)

		# RM needs to arrive by parent SFG schedule_date
		# custom_start_date = when to order = schedule - lead_time - grn_days
		mr_row.schedule_date = earliest_sfg_schedule
		mr_row.custom_start_date = add_days(getdate(earliest_sfg_schedule), -(lead_time_days + grn_days_mr))

		# Backdating: if custom_start_date < today, shift forward
		if not allow_backdated and getdate(mr_row.custom_start_date) < today:
			mr_row.custom_start_date = today_dt
			receive_date = add_days(today, lead_time_days)
			mr_row.schedule_date = _to_datetime(get_holiday_adjusted_date(receive_date, grn_days_mr, holiday_list))

	# ── STEP 3b: Propagate RM delays → SFG → (then STEP 4 pushes to FG) ──
	# If an RM schedule_date > its parent SFG's schedule_date, the SFG can't
	# start until the RM arrives.  Push SFG forward preserving its duration,
	# then cascade up through nested SFGs.
	rm_schedules: dict[str, Any] = {}
	for mr_row in doc.mr_items:
		if mr_row.sales_order == so_name and mr_row.schedule_date:
			rm_schedules[mr_row.item_code] = getdate(mr_row.schedule_date)

	if rm_schedules:
		# bom_no → max RM schedule_date that BOM depends on
		bom_to_max_rm: dict[str, Any] = {}
		for bom_no, rm_set in bom_item_links.items():
			for rm_code in rm_set:
				if rm_code in rm_schedules:
					if bom_no not in bom_to_max_rm or rm_schedules[rm_code] > bom_to_max_rm[bom_no]:
						bom_to_max_rm[bom_no] = rm_schedules[rm_code]

		# Build SFG working map — carries scheduling params from PASS 1
		# Use datetimes throughout so the cascade preserves exact shift times.
		sfg_map: dict[str, dict[str, Any]] = {}
		for data in item_data.values():
			row = data["row"]
			if row.schedule_date and row.custom_schedule_end_date:
				sfg_map[row.production_item] = {
					"row":              row,
					"schedule_date":    get_datetime(row.schedule_date),
					"end_date":         get_datetime(row.custom_schedule_end_date),
					"parent_item_code": row.parent_item_code,
					"bom_no":          row.bom_no,
					# Scheduling params for shift-aware end-date recomputation
					"time_type":       data["time_type"],
					"prod_mins":       data["prod_mins"],
					"lead_time":       data["lead_time"],
					"grn_days":        data["grn_days"],
				}

		def _sfg_end_dt(start_dt_: Any, sdata_: dict) -> datetime:
			"""Compute shift-aware end datetime for one SFG after a cascade push."""
			if sdata_["time_type"] == "lead_time":
				lt = sdata_["lead_time"]
				grn = sdata_["grn_days"]
				end_raw = getdate(add_days(getdate(start_dt_), lt))
				end_d = getdate(get_holiday_adjusted_date(end_raw, grn, holiday_list))
				return datetime.combine(end_d, datetime.min.time()) + shift_start_td
			else:
				pmins = sdata_["prod_mins"]
				if pmins > 0:
					return shift_aware_forward_schedule(get_datetime(start_dt_), pmins, shift_config)
				return get_datetime(start_dt_)

		# Push SFGs whose BOM has a delayed RM
		sfg_changed = False
		for item, sdata in sfg_map.items():
			if sdata["bom_no"] not in bom_to_max_rm:
				continue
			rm_max = bom_to_max_rm[sdata["bom_no"]]  # date
			rm_max_dt = datetime.combine(rm_max, datetime.min.time()) + shift_start_td
			if rm_max > getdate(sdata["schedule_date"]):
				sdata["schedule_date"] = rm_max_dt
				sdata["end_date"] = _sfg_end_dt(rm_max_dt, sdata)
				sfg_changed = True

		# Backward propagation among SFGs — child end > parent start → push parent
		if sfg_changed:
			for _iter in range(10):
				changes = False
				for item, sdata in sfg_map.items():
					parent = sdata["parent_item_code"]
					if parent not in sfg_map:
						continue
					pdata = sfg_map[parent]
					if sdata["end_date"] > pdata["schedule_date"]:
						pdata["schedule_date"] = sdata["end_date"]
						pdata["end_date"] = _sfg_end_dt(sdata["end_date"], pdata)
						changes = True
				if not changes:
					break

			# Apply updated datetimes back to SFG rows
			for item, sdata in sfg_map.items():
				sdata["row"].schedule_date = sdata["schedule_date"]
				sdata["row"].custom_schedule_end_date = sdata["end_date"]

	# ── STEP 4: Enforce FG planned_start >= top-level SFG end_dates ───
	for fg_row in doc.po_items:
		if fg_row.sales_order != so_name:
			continue

		max_sfg_end = None
		for sfg_row in doc.sub_assembly_items:
			if sfg_row.sales_order == so_name and sfg_row.parent_item_code == fg_row.item_code:
				if sfg_row.custom_schedule_end_date:
					sfg_end = get_datetime(sfg_row.custom_schedule_end_date)
					if max_sfg_end is None or sfg_end > max_sfg_end:
						max_sfg_end = sfg_end

		if max_sfg_end and max_sfg_end > get_datetime(fg_row.planned_start_date):
			fg_row.planned_start_date = max_sfg_end
			fg_prod_mins_s4 = _calculate_production_minutes(
				fg_row.bom_no, flt(fg_row.planned_qty), fg_bom_cache_for_cascade
			)
			if fg_prod_mins_s4 > 0:
				fg_row.custom_planned_end_date = str(
					shift_aware_forward_schedule(max_sfg_end, fg_prod_mins_s4, shift_config)
				)
			else:
				fg_row.custom_planned_end_date = str(max_sfg_end)


@frappe.whitelist()
def create_production_plans_async(bulk_pp_name):
	"""
	Create Production Plans asynchronously - one per sales order

	Args:
		bulk_pp_name: Name of the Bulk Pre Production Plan
	"""
	bulk_pp = frappe.get_doc("Bulk Pre Production Plan", bulk_pp_name)

	if not bulk_pp.sales_orders:
		return

	created_plans = []
	errors = []

	for so_row in bulk_pp.sales_orders:
		if not so_row.is_selected:
			continue

		try:
			# Create Production Plan for this sales order
			production_plan = create_production_plan_for_sales_order(bulk_pp, so_row.sales_order)
			created_plans.append(production_plan.name)

		except Exception as e:
			frappe.log_error(
				title=f"Error creating Production Plan for {so_row.sales_order}",
				message=frappe.get_traceback()
			)
			errors.append(f"{so_row.sales_order}: {str(e)}")

	# Notify user
	if created_plans:
		message = _("Successfully created {0} Production Plan(s)").format(len(created_plans))
		if errors:
			message += _("<br><br>Errors: {0}").format("<br>".join(errors))

		frappe.publish_realtime(
			event="msgprint",
			message=message,
			user=frappe.session.user
		)

		# Also send notification
		frappe.publish_realtime(
			event="show_alert",
			message={
				"message": _("{0} Production Plans created from {1}").format(len(created_plans), bulk_pp_name),
				"indicator": "green"
			},
			user=frappe.session.user
		)


def create_production_plan_for_sales_order(bulk_pp, sales_order):
	"""
	Create a Production Plan for a specific sales order using direct DB inserts
	No controller methods are triggered - user can modify later

	Args:
		bulk_pp: Bulk Pre Production Plan document
		sales_order: Sales Order name

	Returns:
		Production Plan name
	"""
	# Get items for this sales order
	fg_items = [item for item in bulk_pp.po_items if item.sales_order == sales_order]
	sfg_items = [item for item in bulk_pp.sub_assembly_items if item.sales_order == sales_order]
	mr_items = [item for item in bulk_pp.mr_items if item.sales_order == sales_order]

	frappe.logger().info(f"Creating PP for {sales_order}: FG={len(fg_items)}, SFG={len(sfg_items)}, MR={len(mr_items)}")

	if not fg_items:
		frappe.throw(_("No items found for Sales Order {0}").format(sales_order))

	# Generate unique name for Production Plan
	from frappe.model.naming import make_autoname
	pp_name = make_autoname("MFG-PLAN-.YYYY.-.#####")

	# Get current timestamp
	now = frappe.utils.now()
	user = frappe.session.user

	# Insert Production Plan parent record directly
	frappe.db.sql("""
		INSERT INTO `tabProduction Plan`
		(name, creation, modified, modified_by, owner, docstatus,
		 company, posting_date, get_items_from, status, custom_bulk_pre_production_plan)
		VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
	""", (
		pp_name,
		now,
		now,
		user,
		user,
		0,  # Draft status
		bulk_pp.company,
		bulk_pp.posting_date,
		"Sales Order",
		"Draft",
		bulk_pp.name  # Reference to Bulk PP
	))

	# Insert sales order reference
	frappe.db.sql("""
		INSERT INTO `tabProduction Plan Sales Order`
		(name, creation, modified, modified_by, owner, docstatus, parent, parenttype, parentfield, idx, sales_order)
		VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
	""", (
		frappe.generate_hash(length=10),
		now,
		now,
		user,
		user,
		0,
		pp_name,
		"Production Plan",
		"sales_orders",
		1,
		sales_order
	))

	# Insert FG items (po_items)
	for idx, fg in enumerate(fg_items, start=1):
		frappe.db.sql("""
			INSERT INTO `tabProduction Plan Item`
			(name, creation, modified, modified_by, owner, docstatus, parent, parenttype, parentfield, idx,
			 item_code, bom_no, planned_qty, planned_start_date, custom_planned_end_date,
			 sales_order, sales_order_item, warehouse, description, stock_uom, product_bundle_item,
			 custom_manufacturing_type)
			VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		""", (
			frappe.generate_hash(length=10),
			now, now, user, user, 0,
			pp_name, "Production Plan", "po_items", idx,
			fg.item_code, fg.bom_no, fg.planned_qty, fg.planned_start_date,
			getattr(fg, 'custom_planned_end_date', None),
			fg.sales_order, fg.sales_order_item, fg.warehouse,
			fg.description, fg.stock_uom, fg.product_bundle_item,
			getattr(fg, 'manufacturing_type', 'In House')
		))

	# Insert SFG items (sub_assembly_items)
	for idx, sfg in enumerate(sfg_items, start=1):
		try:
			frappe.db.sql("""
				INSERT INTO `tabProduction Plan Sub Assembly Item`
				(name, creation, modified, modified_by, owner, docstatus, parent, parenttype, parentfield, idx,
				 production_item, bom_no, qty, schedule_date,
				 type_of_manufacturing, supplier, stock_uom, description,
				 custom_schedule_end_date, parent_item_code)
				VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
			""", (
				frappe.generate_hash(length=10),
				now, now, user, user, 0,
				pp_name, "Production Plan", "sub_assembly_items", idx,
				sfg.production_item,
				getattr(sfg, 'bom_no', None),
				getattr(sfg, 'qty', 0),
				getattr(sfg, 'schedule_date', None),
				getattr(sfg, 'type_of_manufacturing', None),
				getattr(sfg, 'supplier', None),
				getattr(sfg, 'stock_uom', None),
				getattr(sfg, 'description', None),
				getattr(sfg, "custom_schedule_end_date", None),
				getattr(sfg, "parent_item_code", None)
			))
		except Exception as e:
			frappe.logger().error(f"Failed to insert SFG item {sfg.production_item}: {str(e)}")
			raise

	# Insert MR items (mr_items)
	for idx, mr in enumerate(mr_items, start=1):
		try:
			frappe.db.sql("""
				INSERT INTO `tabMaterial Request Plan Item`
				(name, creation, modified, modified_by, owner, docstatus, parent, parenttype, parentfield, idx,
				 item_code, quantity, warehouse, schedule_date, uom,
				 description, item_name, min_order_qty, custom_start_date, custom_supplier,
				 material_request_type, required_bom_qty)
				VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
			""", (
				frappe.generate_hash(length=10),
				now, now, user, user, 0,
				pp_name, "Production Plan", "mr_items", idx,
				mr.item_code,
				getattr(mr, 'quantity', 0),
				getattr(mr, 'warehouse', None),
				getattr(mr, 'schedule_date', None),
				getattr(mr, 'uom', None),
				getattr(mr, 'description', None),
				getattr(mr, 'item_name', None),
				getattr(mr, 'min_order_qty', None),
				getattr(mr, "custom_start_date", None),
				getattr(mr, "custom_supplier", None),
				getattr(mr, "material_request_type", "Purchase"),
				getattr(mr, "required_bom_qty", 0)
			))
		except Exception as e:
			frappe.logger().error(f"Failed to insert MR item {mr.item_code}: {str(e)}")
			raise

	frappe.db.commit()

	# Return a simple dict with the name
	return frappe._dict({"name": pp_name})


@frappe.whitelist()
def get_bulk_pp_for_production_plan(production_plan):
	"""
	Get Bulk Pre Production Plan reference for a Production Plan

	Args:
		production_plan: Production Plan name

	Returns:
		dict with Bulk PP details or None
	"""
	# Get the Bulk PP reference from custom field
	bulk_pp_name = frappe.db.get_value(
		"Production Plan",
		production_plan,
		"custom_bulk_pre_production_plan"
	)

	if not bulk_pp_name:
		return None

	# Get Bulk PP details
	bulk_pp = frappe.get_doc("Bulk Pre Production Plan", bulk_pp_name)

	# Get sales order from Production Plan's sales_orders table
	sales_order = frappe.db.get_value(
		"Production Plan Sales Order",
		{"parent": production_plan},
		"sales_order"
	)

	return {
		"bulk_pp": bulk_pp.name,
		"sales_order": sales_order,
		"posting_date": bulk_pp.posting_date,
		"status": bulk_pp.status,
		"company": bulk_pp.company
	}
