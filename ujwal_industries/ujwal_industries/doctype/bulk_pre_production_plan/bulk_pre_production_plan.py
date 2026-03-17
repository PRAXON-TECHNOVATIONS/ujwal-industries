# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import frappe
import json
from frappe import _, msgprint
from frappe.model.document import Document
from frappe.utils import getdate, get_datetime, add_to_date, add_days, now_datetime, flt, cint
from typing import Any
import math
from datetime import datetime, timedelta
import json

# Import helper functions from production_plan overrides
from ujwal_industries.ujwal_industries.overrides.pp_utils import (
	_get_allow_backdated_setting,
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


@frappe.whitelist()
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


def _get_default_bom_for_item(item_code: str) -> str | None:
	"""Return the active default BOM for an item."""
	return frappe.db.get_value(
		"BOM",
		{
			"item": item_code,
			"is_active": 1,
			"is_default": 1,
			"docstatus": 1,
		},
		"name",
	)


def _get_bom_spm(bom_no: str | None) -> int:
	"""Default SPM = first operation batch size x default workstation count."""
	return cint(_get_bom_spm_details_map(bom_no).get("spm") or 0)


def _parse_csv_list(csv_value: str | None) -> list[str]:
	"""Split a CSV string into non-empty trimmed values."""
	if not csv_value:
		return []
	return [value.strip() for value in str(csv_value).split(",") if value and value.strip()]


def _join_csv_list(values: list[str]) -> str:
	"""Join workstation values back to a CSV string."""
	return ",".join(_parse_csv_list(",".join(values or [])))


def _normalise_bom_tool_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
	"""Normalise BOM tool rows from custom_tool_details."""
	result: list[dict[str, Any]] = []
	for row in rows or []:
		result.append({
			"tool": (row or {}).get("tool") or "",
			"tool_load_qty": cint((row or {}).get("tool_load_quantity") or (row or {}).get("tool_load_qty") or 0),
			"operation": (row or {}).get("operation") or "",
			"is_default": cint((row or {}).get("is_default") or 0),
			"pm_days": cint((row or {}).get("pm_days") or (row or {}).get("custom_required_maintenance_days") or 0),
		})
	return result


def _get_bom_tool_rows(bom_no: str | None) -> list[dict[str, Any]]:
	"""Return tool rows configured on a BOM."""
	if not bom_no:
		return []

	rows = frappe.db.sql(
		"""
		SELECT
			td.tool,
			td.tool_load_quantity,
			td.operation,
			td.is_default,
			COALESCE(asset.custom_required_maintenance_days, 0) AS pm_days
		FROM `tabTool Child Table` td
		LEFT JOIN `tabAsset` asset ON asset.name = td.tool
		WHERE td.parent = %(bom_no)s
		ORDER BY td.is_default DESC, td.idx ASC
		""",
		{"bom_no": bom_no},
		as_dict=True,
	)
	return _normalise_bom_tool_rows(rows)


def _get_bom_fallback_lot_capacity(bom_no: str | None) -> int:
	"""Return BOM fixed lot capacity when tools are not configured."""
	if not bom_no:
		return 0
	return cint(
		frappe.db.sql(
			"""
			SELECT MAX(custom_fixed_lot_capacity)
			FROM `tabBOM Operation`
			WHERE parent = %(bom_no)s
			""",
			{"bom_no": bom_no},
		)[0][0]
		or 0
	)


def _resolve_bom_tool_info(
	tool_rows: list[dict[str, Any]] | None,
	selected_tool: str | None = None,
	fallback_lot_capacity: int = 0,
) -> dict[str, Any]:
	"""Resolve effective tool/load/PM details for a row."""
	tools = _normalise_bom_tool_rows(tool_rows)
	selected_tool = (selected_tool or "").strip()
	chosen = None

	if selected_tool:
		chosen = next((row for row in tools if row.get("tool") == selected_tool), None)

	if not chosen and tools:
		chosen = next((row for row in tools if cint(row.get("is_default")) == 1), None) or tools[0]

	if chosen:
		return {
			"tool": chosen.get("tool") or "",
			"tool_load_qty": cint(chosen.get("tool_load_qty") or 0),
			"pm_days": cint(chosen.get("pm_days") or 0),
			"operation": chosen.get("operation") or "",
			"tools": tools,
			"has_tool_rows": 1,
		}

	return {
		"tool": "",
		"tool_load_qty": cint(fallback_lot_capacity or 0),
		"pm_days": 0,
		"operation": "",
		"tools": tools,
		"has_tool_rows": 0,
	}


def _get_bom_spm_details_map(
	bom_no: str | None,
	selected_workstations_csv: str | None = None,
	selected_tool: str | None = None,
) -> dict[str, Any]:
	"""Return first-operation batch size, workstation defaults, and effective SPM."""
	if not bom_no:
		return {
			"bom_no": "",
			"batchsize": 0,
			"workstations_csv": "",
			"workstations": [],
			"selected_workstations_csv": "",
			"machine_count": 0,
			"spm": 0,
			"tool": "",
			"tool_load_qty": 0,
			"pm_days": 0,
			"tools": [],
		}

	rows = frappe.db.sql(
		"""
		SELECT custom_batchsize, custom_workstations_csv
		FROM `tabBOM Operation`
		WHERE parent = %(bom_no)s
		ORDER BY idx ASC
		LIMIT 1
		""",
		{"bom_no": bom_no},
		as_dict=True,
	)
	row = rows[0] if rows else {}
	batchsize = cint((row or {}).get("custom_batchsize") or 0)
	default_workstations = _parse_csv_list((row or {}).get("custom_workstations_csv"))
	selected_workstations = _parse_csv_list(selected_workstations_csv)
	effective_workstations = selected_workstations or default_workstations
	machine_count = len(effective_workstations)
	if batchsize and machine_count <= 0:
		machine_count = 1
	spm = batchsize * machine_count if batchsize else 0
	tool_info = _resolve_bom_tool_info(
		_get_bom_tool_rows(bom_no),
		selected_tool=selected_tool,
		fallback_lot_capacity=_get_bom_fallback_lot_capacity(bom_no),
	)

	return {
		"bom_no": bom_no,
		"batchsize": batchsize,
		"workstations_csv": _join_csv_list(default_workstations),
		"workstations": default_workstations,
		"selected_workstations_csv": _join_csv_list(effective_workstations),
		"machine_count": machine_count,
		"spm": spm,
		"tool": tool_info.get("tool") or "",
		"tool_load_qty": cint(tool_info.get("tool_load_qty") or 0),
		"pm_days": cint(tool_info.get("pm_days") or 0),
		"tools": tool_info.get("tools") or [],
	}


def _get_row_spm_details(
	row: Any,
	bom_no: str | None,
	bom_ops_map: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
	"""Return effective workstation CSV and SPM for a Bulk Pre FG/SFG row."""
	ops = (bom_ops_map or {}).get(bom_no or "", [])
	if ops:
		first_op = ops[0]
		batchsize = cint(first_op.get("custom_batchsize") or 0)
		default_workstations = _parse_csv_list(first_op.get("custom_workstations_csv"))
	else:
		return _get_bom_spm_details_map(
			bom_no,
			getattr(row, "custom_workstations_csv", "") or None,
			getattr(row, "tool", "") or None,
		)

	selected_workstations = _parse_csv_list(getattr(row, "custom_workstations_csv", "") or None)
	effective_workstations = selected_workstations or default_workstations
	machine_count = len(effective_workstations)
	if batchsize and machine_count <= 0:
		machine_count = 1
	spm = batchsize * machine_count if batchsize else 0
	per_shift_qty = 0
	if row.doctype == 'Bulk PP Sub Assembly Item' and row.type_of_manufacturing == 'Subcontract':
		spm = 0
		supplier_sub_details = frappe.db.sql("""
                           SELECT 
								IFNULL(tiss.per_day_qty, 0) as per_day_qty,
								tiss.is_per_day_qty_based,
								IFNULL(tiss.lead_time_days, 0) as lead_time_days
							FROM tabItem ti
							Left JOIN `tabItem Subcontracting Supplier` tiss ON tiss.parent = ti.name 
							WHERE tiss.is_default = 1
							And ti.name = '{0}'
                      """.format(row.production_item), as_dict=True)
		for i in supplier_sub_details:
			if i.get('is_per_day_qty_based') == 1:
				spm = i.get('per_day_qty')/600 if i.get('per_day_qty') != 0 else 0
				per_shift_qty = i.get('per_day_qty') if i.get('per_day_qty') != 0 else 0

	return {
		"bom_no": bom_no or "",
		"batchsize": batchsize,
		"workstations_csv": _join_csv_list(default_workstations),
		"workstations": default_workstations,
		"selected_workstations_csv": _join_csv_list(effective_workstations),
		"machine_count": machine_count,
		"spm": spm,
		"subcontract_per_shift_qty" :per_shift_qty

	}


def _calculate_row_production_minutes(
	row: Any,
	qty: float,
	bom_time_cache: dict[str, list[dict[str, Any]]],
) -> float:
	"""Calculate production minutes using selected/default workstation count for the row."""
	bom_no = getattr(row, "bom_no", None)
	if not bom_no or bom_no not in bom_time_cache:
		return 0.0

	operations = bom_time_cache[bom_no]
	if not operations:
		return 0.0

	machine_count = _get_row_spm_details(row, bom_no, bom_time_cache).get("machine_count") or 1
	total_minutes = 0.0

	for op in operations:
		time_in_mins = float(op.get("time_in_mins") or 0)
		batchsize = float(op.get("custom_batchsize") or 0)
		effective_spm = batchsize * machine_count if batchsize > 0 else 0

		if effective_spm <= 0:
			effective_spm = 1

		total_minutes += (time_in_mins / effective_spm) * float(qty or 0)

	return total_minutes


def _ensure_default_workstations_on_doc(doc: Document) -> None:
	"""Backfill missing workstation CSV on FG/SFG rows from the BOM first operation."""
	for row in list(doc.get("po_items") or []) + list(doc.get("sub_assembly_items") or []):
		if not getattr(row, "bom_no", None) or getattr(row, "custom_workstations_csv", None):
			continue
		details = _get_bom_spm_details_map(row.bom_no)
		if details.get("workstations_csv"):
			row.custom_workstations_csv = details.get("workstations_csv")


def _ensure_default_tools_on_doc(doc: Document) -> None:
	"""Backfill missing tool/load/PM values from the BOM default tool."""
	for row in list(doc.get("po_items") or []) + list(doc.get("sub_assembly_items") or []):
		if not getattr(row, "bom_no", None):
			continue
		details = _get_bom_spm_details_map(row.bom_no, selected_tool=getattr(row, "tool", "") or None)
		if details.get("tool") and not getattr(row, "tool", None):
			row.tool = details.get("tool")
		row.tool_load_qty = cint(details.get("tool_load_qty") or 0)
		row.pm_days = cint(details.get("pm_days") or 0)


def _apply_parallel_dates_to_rows(doc: Document, schedule: dict) -> None:
	"""Write parallel batch schedule dates directly to DB child rows via set_value."""
	for so_data in (schedule or {}).values():
		for fg_data in so_data.get("fg") or []:
			row_name = (fg_data or {}).get("row_name")
			if not row_name:
				continue
			frappe.db.set_value("Bulk PP Item", row_name, {
				"planned_start_date":      fg_data.get("planned_start_date"),
				"custom_planned_end_date": fg_data.get("custom_planned_end_date"),
			})

		for sfg_data in so_data.get("sfg_chain") or []:
			row_name = (sfg_data or {}).get("row_name")
			if not row_name:
				continue
			batches = sfg_data.get("batches") or []
			if batches:
				frappe.db.set_value("Bulk PP Sub Assembly Item", row_name, {
					"schedule_date":            batches[0]["start_date"],
					"custom_schedule_end_date": batches[-1]["end_date"],
				})

		for mr_data in so_data.get("mr") or []:
			row_name = (mr_data or {}).get("row_name")
			if not row_name:
				continue
			frappe.db.set_value("Bulk PP Material Request Item", row_name, {
				"custom_start_date": mr_data.get("start_date"),
				"schedule_date":     mr_data.get("end_date"),
			})


def _apply_parallel_schedule_overrides_to_doc(doc: Document) -> None:
	"""Apply UI-edited BOM/workstation/tool selections from custom_batch_schedule back to child rows."""
	if not getattr(doc, "custom_batch_schedule", None):
		return

	try:
		schedule = json.loads(doc.custom_batch_schedule)
	except Exception:
		return

	fg_map = {row.name: row for row in doc.get("po_items") or [] if getattr(row, "name", None)}
	sfg_map = {row.name: row for row in doc.get("sub_assembly_items") or [] if getattr(row, "name", None)}

	for so_data in (schedule or {}).values():
		for fg_data in so_data.get("fg") or []:
			row = fg_map.get((fg_data or {}).get("row_name"))
			if not row:
				continue
			if fg_data.get("bom_no"):
				row.bom_no = fg_data.get("bom_no")
			if fg_data.get("custom_workstations_csv"):
				row.custom_workstations_csv = fg_data.get("custom_workstations_csv")
			if "tool" in fg_data:
				row.tool = fg_data.get("tool") or ""

		for sfg_data in so_data.get("sfg_chain") or []:
			row = sfg_map.get((sfg_data or {}).get("row_name"))
			frappe.logger().info(
				f"[SPM DEBUG OVERRIDE] sfg_data row_name={sfg_data.get('row_name')} | "
				f"found_row={row.name if row else 'NONE'} | "
				f"sfg_data.custom_workstations_csv='{sfg_data.get('custom_workstations_csv', '')}' | "
				f"row.custom_workstations_csv='{getattr(row, 'custom_workstations_csv', '') if row else 'N/A'}'"
			)
			if not row:
				continue
			if sfg_data.get("bom_no"):
				row.bom_no = sfg_data.get("bom_no")
			if sfg_data.get("custom_workstations_csv"):
				row.custom_workstations_csv = sfg_data.get("custom_workstations_csv")
			if "tool" in sfg_data:
				row.tool = sfg_data.get("tool") or ""


def _get_selected_bom_map(doc: Document, so_name: str) -> dict[str, str]:
	"""Map Sales Order Item row name to user-selected BOM."""
	selected_boms: dict[str, str] = {}

	for row in doc.get("bom_selections") or []:
		if row.sales_order == so_name and row.sales_order_item and row.bom_no:
			selected_boms[row.sales_order_item] = row.bom_no

	return selected_boms


def _get_existing_fg_workstation_map(doc: Document, so_name: str) -> dict[str, dict[str, str]]:
	"""Map SO item row name to selected FG overrides plus the BOM it belonged to."""
	result: dict[str, dict[str, str]] = {}
	for row in doc.get("po_items") or []:
		if row.sales_order != so_name or not row.sales_order_item:
			continue
		if getattr(row, "custom_workstations_csv", None) or getattr(row, "tool", None):
			result[row.sales_order_item] = {
				"bom_no": getattr(row, "bom_no", "") or "",
				"custom_workstations_csv": getattr(row, "custom_workstations_csv", "") or "",
				"tool": getattr(row, "tool", "") or "",
			}
	return result


def _get_existing_sfg_workstation_map(doc: Document, so_name: str) -> dict[tuple[str, str, int, str], dict[str, str]]:
	"""Map SFG identity to selected workstation/tool overrides so regenerate can retain them."""
	result: dict[tuple[str, str, int, str], dict[str, str]] = {}
	for row in doc.get("sub_assembly_items") or []:
		if row.sales_order != so_name:
			continue
		key = (
			getattr(row, "fg_item_code", "") or "",
			getattr(row, "production_item", "") or "",
			cint(getattr(row, "bom_level", 0) or 0),
			getattr(row, "bom_no", "") or "",
		)
		result[key] = {
			"custom_workstations_csv": getattr(row, "custom_workstations_csv", "") or "",
			"tool": getattr(row, "tool", "") or "",
		}
	return result


def _get_item_default_warehouse_map(item_codes: list[str], company: str) -> dict[str, str]:
	"""Return company-specific Item Default.default_warehouse by item."""
	item_codes = list(dict.fromkeys([item_code for item_code in (item_codes or []) if item_code]))
	if not item_codes or not company:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT parent AS item_code, default_warehouse
		FROM `tabItem Default`
		WHERE
			parent IN %(items)s
			AND company = %(company)s
			AND default_warehouse IS NOT NULL
			AND default_warehouse != ''
		""",
		{"items": item_codes, "company": company},
		as_dict=True,
	)
	return {row.item_code: row.default_warehouse for row in rows}


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
		# frappe.enqueue(
		# 	"ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.create_production_plans_async",
		# 	bulk_pp_name=self.name,
		# 	timeout=3000,
		# 	queue="long"
		# )

		# frappe.msgprint(
		# 	_("Production Plans are being created in the background. You will be notified once complete."),
		# 	indicator="blue",
		# 	alert=True
		# )

		frappe.enqueue(
			"ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan.create_production_plans_document",
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
def get_sales_order_item_bom_rows(sales_orders: str | list[str], docname: str | None = None) -> list[dict[str, Any]]:
	"""Return SO item rows with BOM/SPM for item-level user selection."""
	sales_orders = frappe.parse_json(sales_orders) if isinstance(sales_orders, str) else sales_orders
	sales_orders = [so for so in (sales_orders or []) if so]

	if not sales_orders:
		return []

	existing_bom_map: dict[str, str] = {}
	existing_spm_map: dict[str, int] = {}
	fg_workstation_map: dict[str, str] = {}
	if docname:
		doc = frappe.get_doc("Bulk Pre Production Plan", docname)
		existing_bom_map = {
			row.sales_order_item: row.bom_no
			for row in doc.get("bom_selections") or []
			if row.sales_order_item and row.bom_no
		}
		existing_spm_map = {
			row.sales_order_item: cint(row.spm)
			for row in doc.get("bom_selections") or []
			if row.sales_order_item and cint(row.spm)
		}
		for fg_row in doc.get("po_items") or []:
			if getattr(fg_row, "sales_order_item", None) and getattr(fg_row, "custom_workstations_csv", None):
				fg_workstation_map[fg_row.sales_order_item] = fg_row.custom_workstations_csv

	rows = frappe.db.sql(
		"""
		SELECT
			soi.name AS sales_order_item,
			soi.parent AS sales_order,
			soi.item_code,
			soi.item_name,
			soi.qty,
			soi.stock_uom,
			soi.bom_no
		FROM `tabSales Order Item` soi
		WHERE
			soi.parent IN %(sales_orders)s
			AND soi.docstatus = 1
		ORDER BY soi.parent, soi.idx
		""",
		{"sales_orders": sales_orders},
		as_dict=True,
	)

	for row in rows:
		row.bom_no = (
			existing_bom_map.get(row.sales_order_item)
			or row.bom_no
			or _get_default_bom_for_item(row.item_code)
		)
		# Use the saved FG custom workstations to compute SPM so that
		# machine-count changes are reflected correctly on reload.
		fg_csv = fg_workstation_map.get(row.sales_order_item)
		if fg_csv:
			row.spm = cint(_get_bom_spm_details_map(row.bom_no, fg_csv).get("spm") or 0)
		elif existing_spm_map.get(row.sales_order_item):
			row.spm = existing_spm_map[row.sales_order_item]
		else:
			row.spm = _get_bom_spm(row.bom_no)

	return rows


@frappe.whitelist()
def get_bom_spm_details(
	bom_no: str,
	selected_workstations_csv: str | None = None,
	selected_tool: str | None = None,
) -> dict[str, Any]:
	"""Return BOM-derived SPM + tool details for the UI."""
	return _get_bom_spm_details_map(bom_no, selected_workstations_csv, selected_tool)


@frappe.whitelist()
def get_active_boms_for_items(item_codes: str | list[str]) -> dict[str, list[str]]:
	"""Return active BOM names grouped by item."""
	item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	item_codes = list(dict.fromkeys([item for item in (item_codes or []) if item]))

	if not item_codes:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT item, name
		FROM `tabBOM`
		WHERE
			item IN %(item_codes)s
			AND is_active = 1
			AND docstatus = 1
		ORDER BY item, is_default DESC, name ASC
		""",
		{"item_codes": item_codes},
		as_dict=True,
	)

	result: dict[str, list[str]] = {}
	for row in rows:
		result.setdefault(row.item, []).append(row.name)
	return result


@frappe.whitelist()
def recalculate_existing_schedule(docname: str, planning_mode: str | None = None) -> dict[str, Any]:
	"""Recalculate dates/schedule using existing FG/SFG rows without regenerating items."""
	doc = frappe.get_doc("Bulk Pre Production Plan", docname)
	mode = planning_mode or doc.custom_planning_mode or "Sequential"
	_apply_parallel_schedule_overrides_to_doc(doc)
	_ensure_default_workstations_on_doc(doc)
	_ensure_default_tools_on_doc(doc)

	selected_sos = [row.sales_order for row in doc.sales_orders if row.is_selected and row.sales_order]
	if not selected_sos:
		selected_sos = list({row.sales_order for row in doc.po_items if getattr(row, "sales_order", None)})

	for so_name in selected_sos:
		calculate_dates_for_sales_order(doc, so_name)

	doc.flags.ignore_mandatory = True
	doc.save()
	doc.flags.ignore_mandatory = False

	if mode == "Parallel":
		schedule = calculate_parallel_batch_schedule(docname)
		# Write child row dates directly to DB (bypasses doc.save() overwrite issue)
		_apply_parallel_dates_to_rows(doc, schedule)
		# Only save parent-level fields — do NOT reload+save full doc (avoids overwriting set_value'd dates)
		frappe.db.set_value("Bulk Pre Production Plan", docname, {
			"custom_batch_schedule": json.dumps(schedule),
			"custom_planning_mode": "Parallel",
		})
		frappe.db.commit()
		return schedule

	return {
		"status": "ok",
		"planning_mode": mode,
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


# ---------------------------------------------------------------------------
# Parallel Batch Schedule API
# ---------------------------------------------------------------------------

@frappe.whitelist()
def calculate_parallel_batch_schedule(docname: str) -> dict:
	"""
	Calculate parallel (pipeline) batch schedule for all SOs in Bulk PP.

	Algorithm:
	  - SFG chain sorted deepest BOM level first → that SFG starts at planning_start_date
	  - Each subsequent SFG starts exactly when SFG[i-1] row-0 ends (pipeline overlap)
	  - Within same SFG: batches separated by PM gap (next_start = prev_end + pm_days)
	  - PM = 0 for last batch of each SFG (no gap after last batch)
	  - 1st row of 1st SFG: no PM before it
	  - FG dates: reuse existing sequential logic (backward schedule from delivery date)
	  - MR: start = deepest SFG row[0].end_date, end = start + grn + lead_time (no PM)

	Returns dict keyed by SO name.
	"""
	doc = frappe.get_doc("Bulk Pre Production Plan", docname)
	_apply_parallel_schedule_overrides_to_doc(doc)
	_ensure_default_workstations_on_doc(doc)
	_ensure_default_tools_on_doc(doc)

	shift_config = _get_effective_shift_config()
	holidays = _get_holiday_set(shift_config.get("holiday_list"))
	allow_backdated = _get_allow_backdated_setting()
	today_dt = _current_shift_datetime(shift_config)

	result = {}

	# Group po_items / sub_assembly_items / mr_items by sales order
	so_map: dict[str, dict] = {}
	for fg in doc.po_items:
		so_map.setdefault(fg.sales_order, {"fg": [], "sfg": [], "mr": []})
		so_map[fg.sales_order]["fg"].append(fg)
	for sfg in doc.sub_assembly_items:
		if sfg.sales_order in so_map:
			so_map[sfg.sales_order]["sfg"].append(sfg)
	for mr in doc.mr_items:
		if mr.sales_order in so_map:
			so_map[mr.sales_order]["mr"].append(mr)

	# Batch-fetch BOM tool details and operation batchsize
	all_bom_nos = list({
		row.bom_no
		for rows in so_map.values()
		for row in rows["sfg"]
		# for row in rows["fg"]
		if getattr(row, "bom_no", None)
	})
 
	all_bom_nos += list({
		row.bom_no
		for rows in so_map.values()
		for row in rows["fg"]
		if getattr(row, "bom_no", None)
	})
	bom_tool_map = _fetch_bom_tool_map(all_bom_nos)     # bom_no → {tools, default_tool, fallback_lot_capacity}
	bom_ops_map  = _fetch_bom_ops_map(all_bom_nos)      # bom_no → [{operation, custom_batchsize}]

	# Batch-fetch item GRN processing days
	all_item_codes = list({
		row.production_item
		for rows in so_map.values()
		for row in rows["sfg"]
		if getattr(row, "production_item", None)
	} | {
		row.item_code
		for rows in so_map.values()
		for row in rows["mr"]
		if getattr(row, "item_code", None)
	})
	grn_map = _fetch_grn_days_map(all_item_codes)         # item_code → grn_days
	lead_map = _fetch_default_lead_time_map(              # item_code → lead_time_days
		[r.item_code for rows in so_map.values() for r in rows["mr"] if getattr(r, "item_code", None)],
		doc.company
	)
	target_warehouse_map = _get_item_default_warehouse_map(
		list({
			row.item_code
			for rows in so_map.values()
			for row in rows["fg"]
			if getattr(row, "item_code", None)
		} | {
			row.production_item
			for rows in so_map.values()
			for row in rows["sfg"]
			if getattr(row, "production_item", None)
		}),
		doc.company,
	)

	shift_minutes = _get_shift_working_minutes(shift_config)

	# Shift boundary timedeltas for snapping batch start/end times.
	# For multi-shift, last_window_end_td is the adjusted end of the final window
	# (e.g. Night 20:00–06:30 → timedelta(hours=30, minutes=30)) so that
	# _snap_end(Apr9) = Apr10 06:30 — the true end of the combined working day.
	_shift_start_td = _as_timedelta(shift_config.get("start_time")) or timedelta(hours=8)
	_shift_end_td   = (
		shift_config.get("last_window_end_td")
		or _as_timedelta(shift_config.get("end_time"))
		or timedelta(hours=17)
	)

	def _snap_start(dt: datetime) -> datetime:
		"""Snap datetime to shift start time on the same date."""
		return datetime.combine(dt.date(), datetime.min.time()) + _shift_start_td

	def _snap_end(dt: datetime) -> datetime:
		"""Snap datetime to shift end time on the same date."""
		return datetime.combine(dt.date(), datetime.min.time()) + _shift_end_td

	for so_name, items in so_map.items():
		so_mr_item_codes = list({
			row.item_code
			for row in items["mr"]
			if getattr(row, "item_code", None)
		})
		sfg_bom_links: dict[str, set[str]] = {}
		sfg_bom_nos = list({
			row.bom_no
			for row in items["sfg"]
			if getattr(row, "bom_no", None)
		})
		if sfg_bom_nos and so_mr_item_codes:
			linked_rm_rows = frappe.db.sql("""
				SELECT parent AS bom_no, item_code
				FROM `tabBOM Item`
				WHERE parent IN %(boms)s AND item_code IN %(items)s
			""", {"boms": sfg_bom_nos, "items": so_mr_item_codes}, as_dict=True)
			for link in linked_rm_rows:
				sfg_bom_links.setdefault(link.bom_no, set()).add(link.item_code)

		# ── Helper: compute all batches for one SFG forward from a given start_dt ──
		def _compute_sfg_batches_fwd(sfg_row, start_dt_b0, batches_qty, effective_spm, per_shift_qty,
		                              grn_days, pm_days, shift_config, holidays, shift_minutes):
			batch_rows = []
			for b_idx, batch_qty in enumerate(batches_qty):
				mfg_days_b = math.ceil(batch_qty / per_shift_qty) if per_shift_qty > 0 else 1
				if b_idx == 0:
					start_dt = get_datetime(start_dt_b0)
				else:
					prev_end = get_datetime(batch_rows[b_idx - 1]["end_date"])
					# Next batch starts exactly when the previous batch ends; only PM days
					# and holidays are allowed to push the date forward.
					start_dt = _working_day_add(prev_end, pm_days, holidays)
				batch_prod_mins = (batch_qty / effective_spm) if effective_spm > 0 else (mfg_days_b * shift_minutes)
				if start_dt.date() in holidays:
					start_dt = start_dt + timedelta(days=1)
				mfg_end_dt = shift_aware_forward_schedule(start_dt, batch_prod_mins, shift_config)
				is_last    = (b_idx == len(batches_qty) - 1)
				end_dt     = mfg_end_dt if (grn_days == 0) else _snap_end(_working_day_add(mfg_end_dt, grn_days, holidays))
    
				holiday_count = 0
				if sfg_row.get('type_of_manufacturing') == 'In House':
					holiday_count = sum(1 for h in holidays if getdate(start_dt) < h <= getdate(end_dt))

				holiday_dates =[]
				if sfg_row.get('type_of_manufacturing') == 'In House':
					for h in holidays:
						if getdate(start_dt) < h <= getdate(end_dt):
							description = frappe.get_value("Holiday",{'holiday_date':h} ,'description')
							holiday_dates.append(h.strftime("%d-%m-%Y") + ' - ' + description)
      
				batch_rows.append({
					"batch": b_idx + 1, "total": len(batches_qty), "qty": batch_qty,
					"mfg_days": mfg_days_b, "grn_days": grn_days,
					"pm_days": 0 if (is_last or b_idx == 0) else pm_days,
					"holiday_count": holiday_count,
					"holiday_hover": holiday_dates, 
					"start_date": str(start_dt), "mfg_end_date": str(mfg_end_dt), "end_date": str(end_dt),
				})
			return batch_rows

		# ── Get FG deadline = SO delivery_date (always fresh, never stale planned_start_date) ──
		_so_del = frappe.db.get_value("Sales Order", so_name, "delivery_date")
		fg_planned_start_dt = get_datetime(_so_del) if _so_del else today_dt
		# If delivery_date is in the past and backdating not allowed → start from today
		if not allow_backdated and fg_planned_start_dt < today_dt:
			fg_planned_start_dt = today_dt

		# ── SFG chain: BACKWARD from FG.planned_start ────────────────────────
		# Process level-0 first (direct child of FG), deepest last.
		# deadline flows: FG.start → SFG_L0.end → SFG_L0.start → SFG_L1.end → ...
		sfg_rows_sorted = sorted(items["sfg"], key=lambda r: r.bom_level or 0)  # level 0 first

		sfg_chain_bwd: list[dict] = []   # [level0, level1, ..., deepest]
		deadline_dt = _snap_start(fg_planned_start_dt)

		for sfg in sfg_rows_sorted:
			bom_no    = sfg.bom_no or ""
			item_code = sfg.production_item
			sales_qty = flt(sfg.qty)
			grn_days  = int(grn_map.get(item_code, 0))

			tool_info = _resolve_bom_tool_info(
				(bom_tool_map.get(bom_no) or {}).get("tools"),
				selected_tool=getattr(sfg, "tool", "") or None,
				fallback_lot_capacity=cint((bom_tool_map.get(bom_no) or {}).get("fallback_lot_capacity") or 0),
			)
			selected_tool = tool_info.get("tool") or ""
   
			item_suppliers = frappe.get_all("Item Subcontracting Supplier",filters={"parent": item_code},fields=["supplier","per_day_qty"])
			supplier_list = [d.supplier for d in item_suppliers]
   
			tool_load_qty = int(tool_info.get("tool_load_qty", 0))
   
			pm_days = 0
			if sfg.type_of_manufacturing in "In House":
				pm_days       = int(tool_info.get("pm_days", 0))

			spm_details  = _get_row_spm_details(sfg, bom_no, bom_ops_map)
    
			base_batchsize = cint(spm_details.get("batchsize") or 0)
			row_spm        = cint(getattr(sfg, "spm", 0) or 0)
			effective_spm  = row_spm if row_spm > 0 else cint(spm_details.get("spm") or 0)
			machine_count  = cint(spm_details.get("machine_count") or 0)
			# per_shift_qty  = effective_spm * shift_minutes if effective_spm and shift_minutes else 0
			if spm_details.get("subcontract_per_shift_qty") != 0:
				per_shift_qty = spm_details.get("subcontract_per_shift_qty")
			else:
				per_shift_qty  = effective_spm * shift_minutes if effective_spm and shift_minutes else 0


			split_qty = tool_load_qty or per_shift_qty
			batches   = _split_batches(sales_qty, split_qty)

			# ── Batch 0: backward schedule from deadline ──────────────────────
			# Parallel SFG chain: backward from mfg_deadline = deadline - grn_days.
			# b0_end is forced to deadline_dt for a tight chain connection.
			batch0_qty       = batches[0]
			batch0_prod_mins = (batch0_qty / effective_spm) if effective_spm > 0 else shift_minutes
			# Subtract grn_days (skipping weekends + holidays) to get the mfg completion deadline
			mfg_deadline = _snap_start(_working_day_subtract(deadline_dt, grn_days, holidays)) \
			               if grn_days > 0 else deadline_dt
			b0_start   = _snap_start(_backward_schedule(mfg_deadline, batch0_prod_mins, shift_config))
			b0_mfg_end = shift_aware_forward_schedule(b0_start, batch0_prod_mins, shift_config)
			# Force b0_end = deadline_dt so the chain is visually tight (SFG_i.end = SFG_(i-1).start)
			b0_end     = deadline_dt

			mfg_days_b0 = math.ceil(batch0_qty / per_shift_qty) if per_shift_qty > 0 else 1
   
			hc_b0 = 0
			if sfg.type_of_manufacturing in "In House":
				hc_b0 = sum(1 for h in holidays if getdate(b0_start) < h <= getdate(b0_end))
    
			batch_rows: list[dict] = [{
				"batch": 1, "total": len(batches), "qty": batch0_qty,
				"mfg_days": mfg_days_b0, "grn_days": grn_days,
				"pm_days": 0,  # First batch: no pm_days (no maintenance needed before the very first run)
				"holiday_count": hc_b0,
				"start_date": str(b0_start), "mfg_end_date": str(b0_mfg_end), "end_date": str(b0_end),
			}]

			# ── Batches 1..N: forward from batch 0 end ────────────────────────
			for b_idx, batch_qty in enumerate(batches[1:], start=1):
				mfg_days_bn = math.ceil(batch_qty / per_shift_qty) if per_shift_qty > 0 else 1
				prev_end    = get_datetime(batch_rows[b_idx - 1]["end_date"])
				start_dt    = _working_day_add(prev_end, pm_days, holidays)
				bp_mins     = (batch_qty / effective_spm) if effective_spm > 0 else (mfg_days_bn * shift_minutes)
				mfg_end_dt  = shift_aware_forward_schedule(start_dt, bp_mins, shift_config)
				is_last     = (b_idx == len(batches) - 1)
				end_dt      = _snap_end(_working_day_add(mfg_end_dt, grn_days, holidays)) \
				              if grn_days > 0 else mfg_end_dt
				hc = 0
				if sfg.type_of_manufacturing in "In House":
					hc = sum(1 for h in holidays if getdate(start_dt) < h <= getdate(end_dt))
	
				holiday_dates =[]
				if sfg.type_of_manufacturing in "In House":
					for h in holidays:
						if getdate(start_dt) < h <= getdate(end_dt):
							description = frappe.get_value("Holiday",{'holiday_date':h} ,'description')
							holiday_dates.append(h.strftime("%d-%m-%Y") + ' - ' + description)
      
				batch_rows.append({
					"batch": b_idx + 1, "total": len(batches), "qty": batch_qty,
					"mfg_days": mfg_days_bn, "grn_days": grn_days,
					"pm_days": 0 if is_last else pm_days,
					"holiday_count": hc,
					"holiday_hover": holiday_dates, 
					"start_date": str(start_dt), "mfg_end_date": str(mfg_end_dt), "end_date": str(end_dt),
				})

			# Next deadline = this SFG's batch[0].start_date
			deadline_dt = b0_start
			sfg_chain_bwd.append({
				"item_code": item_code, "bom_no": bom_no,
				"tool": selected_tool, "tools": tool_info.get("tools") or [],
				"bom_level": sfg.bom_level or 0, "qty": sales_qty,
				"batchsize": base_batchsize, 
    			"spm": effective_spm,
    			"spm_1": effective_spm,
				"machine_count": machine_count,
				"custom_workstations_csv": spm_details.get("selected_workstations_csv") or "",
				"per_shift_qty": per_shift_qty, "tool_load_qty": tool_load_qty, "pm_days": pm_days,
				"type_of_manufacturing": sfg.type_of_manufacturing or "In House",
				"target_warehouse": getattr(sfg, "fg_warehouse", "") or target_warehouse_map.get(item_code, ""),
				"supplier": sfg.supplier or "", "supplier_list": supplier_list,
    			"row_name": sfg.name, "batches": batch_rows,
			})

		# ── Backdate cascade: deepest SFG start < today → push forward ───────
		# sfg_chain_bwd[-1] = deepest (last processed), sfg_chain_bwd[0] = level 0
		sfg_chain_out: list[dict] = []
		fg_start_override: "datetime | None" = None
		deepest_sfg_has_linked_rm = bool(
			sfg_chain_bwd
			and sfg_bom_links.get(sfg_chain_bwd[-1].get("bom_no") or "")
		)

		if sfg_chain_bwd and (
			get_datetime(sfg_chain_bwd[-1]["batches"][0]["start_date"]) < today_dt
			or not deepest_sfg_has_linked_rm
		):
			# If the deepest SFG has no BOM-linked RM rows in this SO, do not hold it
			# for MR timing; start it from the current shift start instead.
			new_start = _snap_start(today_dt)
			for sfg_data in reversed(sfg_chain_bwd):   # deepest → level 0
				ic_f  = sfg_data["item_code"]
				gd_f  = int(grn_map.get(ic_f, 0))
				espm  = sfg_data["spm"]
				psq   = sfg_data["per_shift_qty"]
				pmd   = sfg_data["pm_days"]
				tlq   = sfg_data["tool_load_qty"]
				blist = _split_batches(sfg_data["qty"], tlq or psq)
				br_f  = _compute_sfg_batches_fwd(sfg_data, new_start, blist, espm, psq, gd_f, pmd,
				                                  shift_config, holidays, shift_minutes)
				entry = dict(sfg_data)
				entry["batches"] = br_f
				sfg_chain_out.append(entry)               # deepest first in output
				new_start = get_datetime(br_f[0]["end_date"])
			# FG must be pushed to after the level-0 SFG's batch[0].end
			fg_start_override = get_datetime(sfg_chain_out[-1]["batches"][0]["end_date"])
		else:
			# No backdate: reverse bwd list so output is deepest-first
			sfg_chain_out = list(reversed(sfg_chain_bwd))

		# top SFG (level 0) batch[0].end = FG start (may be overridden by cascade)
		top_sfg_batch0_end = (
			str(fg_start_override) if fg_start_override
			else (sfg_chain_bwd[0]["batches"][0]["end_date"] if sfg_chain_bwd else None)
		)
		# ── MR: backward schedule from deepest SFG batch[0].start ─────────────
		# Material must ARRIVE by the time deepest SFG starts its first batch.
		# rm_end (Receive By) = deepest SFG batch[0].start
		# rm_start (Order By) = rm_end - (grn_days + lead_days) working days backward
		# If rm_start < today → can't go back → push forward from today,
		#   and cascade-shift the entire SFG chain + FG by the delay.
		deepest_sfg_batch0_start = (
			get_datetime(sfg_chain_out[0]["batches"][0]["start_date"])
			if sfg_chain_out and sfg_chain_out[0]["batches"]
			else None
		)

		max_mr_end_dt: "datetime | None" = None
		mr_rows_out: list[dict] = []
		for mr in items["mr"]:
			item_code  = mr.item_code
			grn_days   = int(grn_map.get(item_code, 0))
			lead_days  = int(lead_map.get(item_code, 0))
			total_days = grn_days + lead_days

			if deepest_sfg_batch0_start:
				# Ideal: receive exactly when deepest SFG starts
				rm_end_ideal   = deepest_sfg_batch0_start
				rm_start_ideal = _working_day_subtract(rm_end_ideal, total_days, holidays)
				if rm_start_ideal < today_dt:
					# Too late to order in time → push MR forward from today
					rm_start = _snap_start(today_dt)
					rm_end   = _snap_end(_working_day_add(today_dt, total_days, holidays))
				else:
					# rm_start_ideal is in the future — order TODAY to get material ASAP.
					# rm_end = today + lead+grn days; SFG cascade will pull production forward.
					rm_start = _snap_start(today_dt)
					rm_end   = _snap_end(_working_day_add(today_dt, total_days, holidays))
			else:
				rm_start = _snap_start(today_dt)
				rm_end   = _snap_end(_working_day_add(today_dt, total_days, holidays))

			rm_end_dt = get_datetime(rm_end) if not isinstance(rm_end, datetime) else rm_end
			if max_mr_end_dt is None or rm_end_dt > max_mr_end_dt:
				max_mr_end_dt = rm_end_dt

			mr_rows_out.append({
				"item_code":  item_code,
				"item_name":  mr.item_name or item_code,
				"qty":        flt(mr.quantity),
				"uom":        mr.uom or "",
				"grn_days":   grn_days,
				"lead_days":  lead_days,
				"start_date": str(rm_start),
				"end_date":   str(rm_end),
				"supplier":   lead_map.get(f"__supplier_{item_code}", ""),
				"row_name":   mr.name,
			})

		# ── Post-MR cascade: material arrives before SFG needs it → pull SFG+FG forward ──
		# If MR ends earlier than the deepest SFG's planned start, re-run the
		# SFG must always start exactly when MR arrives (material available).
		# Cascade runs whether MR arrives early (pull forward) or late (push forward).
		if max_mr_end_dt and sfg_chain_out:
			new_start = _snap_start(max_mr_end_dt)
			sfg_chain_rebuilt: list[dict] = []
			for sfg_data in sfg_chain_out:   # deepest-first
				ic_f  = sfg_data["item_code"]
				gd_f  = int(grn_map.get(ic_f, 0))
				espm  = sfg_data["spm"]
				psq   = sfg_data["per_shift_qty"]
				pmd   = sfg_data["pm_days"]
				tlq   = sfg_data["tool_load_qty"]
				blist = _split_batches(sfg_data["qty"], tlq or psq)
				br_f  = _compute_sfg_batches_fwd(sfg_data, new_start, blist, espm, psq, gd_f, pmd,
				                                  shift_config, holidays, shift_minutes)
				entry = dict(sfg_data)
				entry["batches"] = br_f
				sfg_chain_rebuilt.append(entry)
				new_start = get_datetime(br_f[0]["end_date"])
			sfg_chain_out = sfg_chain_rebuilt
			fg_start_override = get_datetime(sfg_chain_out[-1]["batches"][0]["end_date"])
			top_sfg_batch0_end = str(fg_start_override)

		# ── FG: start = top_sfg_batch0_end (already set above) ─────────────────

		fg_rows_out: list[dict] = []
		_fg_bom_nos = [fg.bom_no for fg in items["fg"] if fg.bom_no]
		_fg_bom_cache = _fetch_bom_operations_cache(_fg_bom_nos) if _fg_bom_nos else {}
		for fg in items["fg"]:
			fg_start = get_datetime(top_sfg_batch0_end) if top_sfg_batch0_end else today_dt
			prod_minutes = _calculate_row_production_minutes(fg, flt(fg.planned_qty), _fg_bom_cache)
			tool_details = _get_bom_spm_details_map(fg.bom_no, selected_tool=getattr(fg, "tool", "") or None)
			if prod_minutes and prod_minutes > 0:
				fg_end = shift_aware_forward_schedule(fg_start, prod_minutes, shift_config)
			else:
				fg_end = fg_start

		fg_rows_sorted =  items["fg"]
		
		prev_fg_row0_end: str | None = None

		for fg_idx, fg in enumerate(fg_rows_sorted):
			bom_no     = fg.bom_no or ""
			item_code  = fg.item_code
			sales_qty  = flt(fg.planned_qty)
			tool_info = _resolve_bom_tool_info(
				(bom_tool_map.get(bom_no) or {}).get("tools"),
				selected_tool=getattr(fg, "tool", "") or None,
				fallback_lot_capacity=cint((bom_tool_map.get(bom_no) or {}).get("fallback_lot_capacity") or 0),
			)
   
			item_suppliers = frappe.get_all("Item Subcontracting Supplier",filters={"parent": item_code},fields=["supplier","per_day_qty"])
			supplier_list = [d.supplier for d in item_suppliers]
   
			selected_tool = tool_info.get("tool") or ""
			tool_load_qty = int(tool_info.get("tool_load_qty", 0))
			pm_days       = int(tool_info.get("pm_days", 0))
			grn_days      = int(grn_map.get(item_code, 0))

   
   
			spm_details = _get_row_spm_details(fg, bom_no, bom_ops_map)
			base_batchsize = cint(spm_details.get("batchsize") or 0)
			# Prefer spm stored on the row (set via workstation selection); fall back to computed
			row_spm = cint(getattr(fg, "spm", 0) or 0)
			effective_spm = row_spm if row_spm > 0 else cint(spm_details.get("spm") or 0)
			machine_count = cint(spm_details.get("machine_count") or 0)
   
			# per_shift_qty
			per_shift_qty = effective_spm * shift_minutes if effective_spm and shift_minutes else 0

			# Split into batches.
			# Prefer tool/fixed-lot capacity; if missing, fall back to one-shift output from SPM.
			split_qty = tool_load_qty or per_shift_qty
			batches = _split_batches(sales_qty, split_qty)
   
			batch_rows: list[dict] = []
			for b_idx, batch_qty in enumerate(batches):
				mfg_days = math.ceil(batch_qty / per_shift_qty) if per_shift_qty > 0 else 1

				# Start date
				if b_idx == 0:
					if fg_idx == 0:
						# First FG, first batch → starts when top SFG batch-0 ends
						start_dt = get_datetime(top_sfg_batch0_end) if top_sfg_batch0_end else today_dt
					else:
						# Multiple FGs: start when prev FG batch-0 ended
						start_dt = get_datetime(prev_fg_row0_end)
				else:
					# Next FG batch starts exactly when the previous batch ends; only PM days
					# and holidays are allowed to push the date forward.
					prev_end = get_datetime(batch_rows[b_idx - 1]["end_date"])
					start_dt = _working_day_add(prev_end, pm_days, holidays)

				batch_prod_mins = (batch_qty / effective_spm) if effective_spm > 0 else (mfg_days * shift_minutes)
				mfg_end_dt = shift_aware_forward_schedule(start_dt, batch_prod_mins, shift_config)
				# grn_days=0 -> available at actual mfg completion; grn_days>0 -> shift_end after grn_days
				end_dt = mfg_end_dt if grn_days == 0 else _snap_end(_working_day_add(mfg_end_dt, grn_days, holidays))

				is_last_batch = (b_idx == len(batches) - 1)
				# Count holidays strictly between start_date and end_date
				holiday_count = sum(
					1 for h in holidays
					if getdate(start_dt) < h <= getdate(end_dt)
				)
    
				# holiday_dates = [
				# 	str(h) for h in holidays
				# 	if getdate(start_dt) < h <= getdate(end_dt)
				# ]
				holiday_dates =[]
				for h in holidays:
					if getdate(start_dt) < h <= getdate(end_dt):
						description = frappe.get_value("Holiday",{'holiday_date':h} ,'description')
						holiday_dates.append(h.strftime("%d-%m-%Y") + ' - ' + description)
    
				batch_rows.append({
					"batch":         b_idx + 1,
					"total":         len(batches),
					"qty":           batch_qty,
					"mfg_days":      mfg_days,
					"grn_days":      grn_days,
					"pm_days":       0 if is_last_batch else pm_days,
					"holiday_count": holiday_count,
					"holiday_hover": holiday_dates, 
					"start_date":    str(start_dt),
					"mfg_end_date":  str(mfg_end_dt),
					"end_date":      str(end_dt),
				})
    
			# Update prev_fg_row0_end for next FG in chain
			if batch_rows:
				prev_fg_row0_end = batch_rows[0]["end_date"]

			fg_rows_out.append({
				"item_code":               fg.item_code,
				"bom_no":                  fg.bom_no or "",
				"tool":                    tool_details.get("tool") or "",
				"tools":                   tool_details.get("tools") or [],
				"tool_load_qty":           cint(tool_details.get("tool_load_qty") or 0),
				"pm_days":                 cint(tool_details.get("pm_days") or 0),
				"sales_order":             fg.sales_order or "",
				"planned_qty":             flt(fg.planned_qty),
				"per_shift_qty":             per_shift_qty,
				"manufacturing_type":      fg.manufacturing_type or "In House",
				# "supplier_list": supplier_list,
				"custom_workstations_csv": getattr(fg, "custom_workstations_csv", "") or "",
				"target_warehouse": (
					getattr(fg, "target_warehouse", "") or target_warehouse_map.get(fg.item_code, "")
				),
				"planned_start_date":      batch_rows[0]["start_date"] if batch_rows else str(fg_start),
				"custom_planned_end_date": batch_rows[-1]["end_date"] if batch_rows else str(fg_end),
				"row_name":                fg.name,
				"batches":                batch_rows,
			})

		result[so_name] = {
			"fg":        fg_rows_out,
			"sfg_chain": sfg_chain_out,
			"mr":        mr_rows_out,
		}
	return result


# ---------------------------------------------------------------------------
# Parallel schedule helpers
# ---------------------------------------------------------------------------

def _working_day_add(from_dt: datetime, n_days: int, holidays: set) -> datetime:
	"""Add n_days skipping holidays only (Sat/Sun are working days here)."""
	if n_days <= 0:
		return from_dt
	from frappe.utils import getdate as _gd, add_days as _ad
	d = _gd(from_dt)
	added = 0
	while added < n_days:
		d = _gd(_ad(d, 1))
		if d not in holidays:
			added += 1
	return datetime.combine(d, from_dt.time())


def _working_day_subtract(from_dt: datetime, n_days: int, holidays: set) -> datetime:
	"""Subtract n_days skipping holidays only (Sat/Sun are working days here)."""
	if n_days <= 0:
		return from_dt
	from frappe.utils import getdate as _gd, add_days as _ad
	d = _gd(from_dt)
	subtracted = 0
	while subtracted < n_days:
		d = _gd(_ad(d, -1))
		if d not in holidays:
			subtracted += 1
	return datetime.combine(d, from_dt.time())


def _get_shift_working_minutes(shift_config: dict) -> int:
	"""Return net working minutes per shift (or total daily minutes across all planning shifts)."""
	# Multi-shift: total_daily_minutes is pre-computed by _get_shift_windows
	if shift_config.get("total_daily_minutes"):
		return int(shift_config["total_daily_minutes"])
	start   = shift_config.get("start_time")
	end     = shift_config.get("end_time")
	l_start = shift_config.get("custom_lunch_start_time")
	l_end   = shift_config.get("custom_lunch_end_time")

	if start is None or end is None:
		return 1440  # fallback: 24hr

	def _td(t):
		if isinstance(t, timedelta):
			return t
		if hasattr(t, "hour"):
			return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
		return timedelta(0)

	shift_td = _td(end) - _td(start)
	lunch_td = timedelta(0)
	if l_start is not None and l_end is not None:
		lunch_td = _td(l_end) - _td(l_start)

	return max(int((shift_td - lunch_td).total_seconds() // 60), 1)


def _split_batches(total_qty: float, batch_qty: int | float) -> list[float]:
	"""Split total_qty into batches of batch_qty. Last batch = remainder."""
	if batch_qty <= 0:
		return [total_qty]
	n = math.ceil(total_qty / batch_qty)
	remainder = total_qty - batch_qty * (n - 1)
	return [float(batch_qty)] * (n - 1) + [float(remainder)]


def _fetch_bom_tool_map(bom_nos: list[str]) -> dict[str, dict]:
	"""
	Returns {bom_no: {tools, default_tool, fallback_lot_capacity}} using:
	  - Tool Child Table rows for user-selectable tool overrides
	  - Fallback lot capacity from BOM Operations when tools are absent
	"""
	if not bom_nos:
		return {}

	rows = frappe.db.sql("""
		SELECT
			td.parent AS bom_no,
			td.tool,
			td.tool_load_quantity,
			td.operation,
			td.is_default,
			COALESCE(asset.custom_required_maintenance_days, 0) AS pm_days
		FROM `tabTool Child Table` td
		LEFT JOIN `tabAsset` asset ON asset.name = td.tool
		WHERE td.parent IN %(bom_nos)s
		ORDER BY td.parent, td.is_default DESC, td.idx ASC
	""", {"bom_nos": bom_nos}, as_dict=True)

	result: dict[str, dict] = {}
	for r in rows:
		entry = result.setdefault(r.bom_no, {
			"tools": [],
			"default_tool": "",
			"fallback_lot_capacity": 0,
		})
		tool_row = _normalise_bom_tool_rows([r])[0]
		entry["tools"].append(tool_row)
		if cint(r.is_default) == 1 and not entry["default_tool"]:
			entry["default_tool"] = r.tool or ""

	# Fallback lot capacity for every BOM
	fallback_rows = frappe.db.sql("""
		SELECT parent AS bom_no, MAX(custom_fixed_lot_capacity) AS lot_capacity
		FROM `tabBOM Operation`
		WHERE parent IN %(bom_nos)s
		  AND custom_fixed_lot_capacity > 0
		GROUP BY parent
	""", {"bom_nos": bom_nos}, as_dict=True)
	for r in fallback_rows:
		entry = result.setdefault(r.bom_no, {
			"tools": [],
			"default_tool": "",
			"fallback_lot_capacity": 0,
		})
		entry["fallback_lot_capacity"] = cint(r.lot_capacity or 0)

	return result


def _fetch_bom_ops_map(bom_nos: list[str]) -> dict[str, list[dict]]:
	"""Returns BOM ops keyed by BOM, including batch size and workstation CSV."""
	if not bom_nos:
		return {}
	rows = frappe.db.sql("""
		SELECT parent AS bom_no, operation, custom_batchsize, custom_workstations_csv, idx
		FROM `tabBOM Operation`
		WHERE parent IN %(bom_nos)s
		ORDER BY parent, idx
	""", {"bom_nos": bom_nos}, as_dict=True)
	result: dict[str, list[dict]] = {}
	for r in rows:
		result.setdefault(r.bom_no, []).append({
			"operation": r.operation,
			"custom_batchsize": cint(r.custom_batchsize or 0),
			"custom_workstations_csv": r.custom_workstations_csv or "",
		})
	return result


def _fetch_grn_days_map(item_codes: list[str]) -> dict[str, int]:
	"""Returns {item_code: custom_expected_grn_processing_days}."""
	if not item_codes:
		return {}
	rows = frappe.db.sql(
		"SELECT name, COALESCE(custom_expected_grn_processing_days, 0) AS grn_days "
		"FROM `tabItem` WHERE name IN %(items)s",
		{"items": item_codes}, as_dict=True
	)
	return {r.name: cint(r.grn_days) for r in rows}


def _fetch_default_lead_time_map(item_codes: list[str], company: str) -> dict[str, int]:
	"""Returns {item_code: lead_time_days} from is_default subcontracting supplier."""
	if not item_codes:
		return {}
	rows = frappe.db.sql("""
		SELECT iss.parent AS item_code, iss.supplier, iss.lead_time_days
		FROM `tabItem Subcontracting Supplier` iss
		WHERE iss.parent IN %(items)s
		  AND iss.is_default = 1
		  AND (iss.company = %(company)s OR iss.company IS NULL OR iss.company = '')
		ORDER BY iss.is_default DESC
	""", {"items": item_codes, "company": company}, as_dict=True)

	result: dict[str, int] = {}
	for r in rows:
		result[r.item_code] = cint(r.lead_time_days or 0)
		result[f"__supplier_{r.item_code}"] = r.supplier or ""
	return result


@frappe.whitelist()
def generate_production_plan_items(docname: str, planning_mode: str | None = None) -> dict[str, Any]:
	"""
	Generate Production Plan items for selected Sales Orders (Bulk PP workflow)

	Args:
		docname: Bulk Pre Production Plan name

	Returns:
		Dict with generated items count
	"""
	doc = frappe.get_doc("Bulk Pre Production Plan", docname)

	if planning_mode:
		doc.custom_planning_mode = planning_mode

	if not doc.sales_orders:
		frappe.throw(_("No Sales Orders found. Please fetch Sales Orders first."))

	# Get selected sales orders
	selected_sos = [row.sales_order for row in doc.sales_orders if row.is_selected]

	if not selected_sos:
		frappe.throw(_("Please select at least one Sales Order"))

	# Clear existing items
	existing_fg_ws_map = {
		row.sales_order: _get_existing_fg_workstation_map(doc, row.sales_order)
		for row in doc.sales_orders if row.sales_order
	}
	existing_sfg_ws_map = {
		row.sales_order: _get_existing_sfg_workstation_map(doc, row.sales_order)
		for row in doc.sales_orders if row.sales_order
	}
	doc.flags.existing_fg_workstation_maps = existing_fg_ws_map
	doc.flags.existing_sfg_workstation_maps = existing_sfg_ws_map
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

	# Compute parallel batch schedule so the parallel tab is ready instantly.
	# Do NOT apply to child rows here — sequential dates must stay in SFG/FG row fields.
	# Parallel dates are written to rows only when the user explicitly runs Parallel mode.
	schedule = calculate_parallel_batch_schedule(docname)
	frappe.db.set_value("Bulk Pre Production Plan", docname, {
		"custom_batch_schedule": json.dumps(schedule),
	})
	frappe.db.commit()

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
	selected_boms = _get_selected_bom_map(doc, so_name)
	for so_row in doc.sales_orders:
		if so_row.sales_order == so_name:
			so_warehouse = so_row.for_warehouse
			break

	# Get Sales Order items
	so_items = frappe.db.sql("""
		SELECT
			soi.name AS sales_order_item,
			soi.item_code,
			soi.qty,
			soi.stock_uom,
			soi.warehouse,
			soi.delivery_date,
			so.delivery_date as so_delivery_date,
			i.is_sub_contracted_item,
			soi.bom_no
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

	target_warehouse_map = _get_item_default_warehouse_map([item.item_code for item in so_items], doc.company)
	existing_fg_ws_map = (getattr(doc.flags, "existing_fg_workstation_maps", {}) or {}).get(so_name, {})


	# Process each SO item
	for item in so_items:
		bom = (
			selected_boms.get(item.sales_order_item)
			or item.bom_no
			or _get_default_bom_for_item(item.item_code)
		)

		if not bom:
			continue

		bom_spm_details = _get_bom_spm_details_map(bom)
		existing_fg_ws = existing_fg_ws_map.get(item.sales_order_item) or {}
		existing_fg_csv = (
			existing_fg_ws.get("custom_workstations_csv")
			if existing_fg_ws.get("bom_no") == bom
			else ""
		)
		existing_fg_tool = (
			existing_fg_ws.get("tool")
			if existing_fg_ws.get("bom_no") == bom
			else ""
		)
		tool_details = _get_bom_spm_details_map(bom, selected_tool=existing_fg_tool or None)

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
			'sales_order_item': item.sales_order_item,
			'item_code': item.item_code,
			'bom_no': bom,
			'tool': tool_details.get('tool') or '',
			'tool_load_qty': cint(tool_details.get('tool_load_qty') or 0),
			'pm_days': cint(tool_details.get('pm_days') or 0),
			'custom_workstations_csv': (
				existing_fg_csv
				or bom_spm_details.get('selected_workstations_csv')
				or bom_spm_details.get('workstations_csv')
				or ''
			),
			'planned_qty': item.qty,
			'stock_uom': item.stock_uom,
			'warehouse': warehouse,
			'target_warehouse': target_warehouse_map.get(item.item_code),
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

	x = {
		'po_items': po_count,
		'sfg_items': sfg_count,
		'mr_items': mr_count
	}
	return x


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
	target_warehouse_map = _get_item_default_warehouse_map(
		[bom_item.item_code for bom_item in bom_items],
		doc.company,
	)
	existing_sfg_ws_map = (getattr(doc.flags, "existing_sfg_workstation_maps", {}) or {}).get(so_name, {})

	for bom_item in bom_items:
		required_qty = bom_item.qty_per_unit * qty

		if bom_item.item_bom_no:
			sfg_key = (
				fg_item or "",
				bom_item.item_code,
				cint(level or 0),
				bom_item.item_bom_no or "",
			)
			existing_sfg = existing_sfg_ws_map.get(sfg_key) or {}
			tool_details = _get_bom_spm_details_map(
				bom_item.item_bom_no,
				selected_tool=existing_sfg.get("tool") or None,
			)
			# Sub assembly item — use actual required_qty (qty_per_unit × parent qty)
			doc.append('sub_assembly_items', {
				'sales_order': so_name,
				'fg_item_code': fg_item,
				'production_item': bom_item.item_code,
				'parent_item_code': parent_item,
				'bom_no': bom_item.item_bom_no,
				'tool': tool_details.get('tool') or '',
				'tool_load_qty': cint(tool_details.get('tool_load_qty') or 0),
				'pm_days': cint(tool_details.get('pm_days') or 0),
				'custom_workstations_csv': (
					existing_sfg.get("custom_workstations_csv")
					or _get_bom_spm_details_map(bom_item.item_bom_no).get('selected_workstations_csv')
				),
				'bom_level': level,
				'qty': required_qty,
				'stock_uom': bom_item.stock_uom,
				'schedule_date': delivery_date,
				'type_of_manufacturing': 'Subcontract' if bom_item.is_sub_contracted_item else 'In House',
				'fg_warehouse': target_warehouse_map.get(bom_item.item_code),
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
	"""Batch fetch BOM operations for row-level production minute calculations."""
	if not bom_nos:
		return {}

	operations_data = frappe.db.sql("""
		SELECT parent as bom_no, time_in_mins, custom_batchsize, custom_workstations_csv, operation, idx
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

	# Always use SO delivery_date as the deadline — never use stale planned_start_date
	_so_delivery_date = frappe.db.get_value("Sales Order", so_name, "delivery_date")

	for fg_row in doc.po_items:
		if fg_row.sales_order != so_name or not fg_row.bom_no:
			continue

		# Use SO delivery_date directly (not stale planned_start_date from previous run)
		delivery_dt = get_datetime(_so_delivery_date) if _so_delivery_date else get_datetime(fg_row.planned_start_date)
		prod_minutes = _calculate_row_production_minutes(fg_row, flt(fg_row.planned_qty), fg_bom_cache)

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
			prod_mins = _calculate_row_production_minutes(
				sfg_row, flt(sfg_row.qty), sfg_bom_cache
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
						fg_prod_mins = _calculate_row_production_minutes(
							po_item, flt(po_item.planned_qty), fg_bom_cache_for_cascade
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
			fg_prod_mins_s4 = _calculate_row_production_minutes(
				fg_row, flt(fg_row.planned_qty), fg_bom_cache_for_cascade
			)
			if fg_prod_mins_s4 > 0:
				fg_row.custom_planned_end_date = str(
					shift_aware_forward_schedule(max_sfg_end, fg_prod_mins_s4, shift_config)
				)
			else:
				fg_row.custom_planned_end_date = str(max_sfg_end)


@frappe.whitelist()
def create_production_plans_document(bulk_pp_name) :
	bulk_pp = frappe.get_doc("Bulk Pre Production Plan", bulk_pp_name)

	if not bulk_pp.sales_orders:
		return

	so_data = json.loads(bulk_pp.custom_batch_schedule)
	for i in so_data:
		pp_doc = frappe.new_doc("Production Plan")
		pp_doc.custom_bulk_pre_production_plan = bulk_pp.name
		pp_doc.get_items_from = 'Sales Order'
		pp_doc.custom_parallel_planning = 1

		pp_doc.append('sales_orders',{
			'sales_order': i
		})
		so_details = so_data.get(i)
		for j in so_details.get('fg'):
			warehouse = ''
			item_doc = frappe.get_doc("Item", j.get('item_code'))
			if item_doc.item_defaults:
					warehouse = item_doc.item_defaults[0].get('default_warehouse')
     
			if 'manufacturing_type' in j:
				types = j.get('manufacturing_type')
			elif "custom_manufacturing_type" in j:
				types = j.get('custom_manufacturing_type')
			else:
				types = 'In House'
	
			for k in j.get('batches'):
				pp_doc.append('po_items',{
					'include_exploded_items' : 1,
					'item_code' : j.get('item_code'),
					'bom_no' : j.get('bom_no'),
					'planned_qty' : k.get('qty'),
					'stock_uom' : item_doc.stock_uom,
					'custom_manufacturing_type' : types,
					'planned_start_date' : k.get('start_date'),
					'custom_planned_end_date' : k.get('end_date'),
					'sales_order' : j.get('sales_order'),
					'warehouse' : warehouse,
					'custom_workstation' : j.get('custom_workstations_csv'),
				})
		
		for j in so_details.get('sfg_chain')[::-1]:
			warehouse = ''
			item_doc = frappe.get_doc("Item",j.get('item_code'))
			if item_doc.item_defaults:
					warehouse = item_doc.item_defaults[0].get('default_warehouse')
			for k in j.get('batches'):
				pp_doc.append('sub_assembly_items',{
					'production_item' : j.get('item_code'),
					'bom_no' : j.get('bom_no'),
					'qty' : k.get('qty'),
					'stock_uom' : item_doc.stock_uom,
					'type_of_manufacturing' : j.get('type_of_manufacturing'),
					'schedule_date' : k.get('start_date'),
					'custom_schedule_end_date' : k.get('end_date'),
					'supplier' : j.get('supplier'),
					'fg_warehouse' : warehouse,
					'custom_workstation' : j.get('custom_workstations_csv'),
				})
		
		for j in so_details.get('mr'):
			warehouse = ''
			item_doc = frappe.get_doc("Item", j.get('item_code'))
			if item_doc.item_defaults:
					warehouse = item_doc.item_defaults[0].get('default_warehouse')
			pp_doc.append('mr_items',{
				'item_code' :  j.get('item_code'),
				'item_name' :  j.get('item_name'),
				'warehouse' :  warehouse,
				'custom_start_date' :  j.get('start_date'),
				'schedule_date' :  j.get('end_date'),
				'quantity' :  j.get('qty'),
				'custom_supplier' :  j.get('supplier'),
			})
		pp_doc.save()
 
 
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
			 sales_order, sales_order_item, warehouse, target_warehouse, description, stock_uom, product_bundle_item,
			 custom_manufacturing_type)
			VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
		""", (
			frappe.generate_hash(length=10),
			now, now, user, user, 0,
			pp_name, "Production Plan", "po_items", idx,
			fg.item_code, fg.bom_no, fg.planned_qty, fg.planned_start_date,
			getattr(fg, 'custom_planned_end_date', None),
			fg.sales_order, fg.sales_order_item, fg.warehouse, getattr(fg, 'target_warehouse', None),
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
				 type_of_manufacturing, supplier, fg_warehouse, stock_uom, description,
				 custom_schedule_end_date, parent_item_code)
				VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
				getattr(sfg, 'fg_warehouse', None),
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
