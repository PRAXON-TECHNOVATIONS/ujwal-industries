# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


def get_last_purchase_rate(item_code):
	return flt(frappe.db.get_value("Item", item_code, "last_purchase_rate"))


def get_last_sales_rate(item_code):
	rate = frappe.db.get_value(
		"Sales Invoice Item",
		{"item_code": item_code, "docstatus": 1},
		"rate",
		order_by="creation desc",
	)
	return flt(rate)


@frappe.whitelist()
def get_last_sales_rate_api(item_code):
	return get_last_sales_rate(item_code)


def get_subcontract_operation_row(item_code, company=None):
	"""If this item has a subcontract row set up on its Item master
	(Purchasing tab → Subcontracting Suppliers, Type = Subcontract, with an
	Operation and Rate per Pc filled in), return it as an Operations row dict
	— since subcontracted steps like Case Hardening or Plating often have no
	BOM Operation of their own (they're bought-in services, not in-house
	machine time). Only one row per (item, company) can be marked Is Default,
	so when `company` is given, this matches strictly on that company — no
	cross-company fallback, since showing a different company's rate/supplier
	would be worse than showing none. Without a company, prefers the row
	marked Is Default across all companies; falls back to the first row that
	has both Operation and Rate set. Returns None if nothing matches."""
	filters = {
		"parent": item_code,
		"parenttype": "Item",
		"custom_type": "Subcontract",
		"custom_operation": ["is", "set"],
	}
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		"Item Subcontracting Supplier",
		filters=filters,
		fields=["custom_operation", "custom_rate_per_pc", "is_default"],
		order_by="is_default desc",
	)
	row = next((r for r in rows if flt(r.custom_rate_per_pc)), None)
	if not row:
		return None

	return {
		"operation": row.custom_operation,
		"workstation": None,
		"time_per_pc_min": 0,
		"rate_per_pc": flt(row.custom_rate_per_pc),
	}


def first_workstation_from_csv(csv_value):
	"""BOM Operation can list several interchangeable machines in
	custom_workstations_csv (e.g. 'UI/MC/94,UI/MC/95,...') when the standard
	single workstation field is left empty. Default to the first one listed
	— the pulled row stays editable if a different machine should be used
	for this estimate."""
	if not csv_value:
		return None
	return csv_value.split(",")[0].strip()


def explode_bom_tree(bom_name, per_pc_qty=1, company=None):
	"""Walk this BOM and every sub-assembly BOM beneath it, returning
	flattened RM/Scrap/Operation rows (plain dicts, not appended to any
	document) scaled to `per_pc_qty` — how many units of *this* BOM's item
	are needed per one finished piece of the top-level item. A sub-assembly's
	own subcontract step (e.g. Case Hardening on item 200632) is the
	operation that turns whatever its own BOM tree produces INTO that item,
	so it's added right after that tree is walked — Operations land in real
	process order (raw material's operations first, each subcontract step
	right after the tree beneath it, working up)."""
	rm_items = []
	scrap_items = []
	operation_items = []

	def _walk(bom_name, per_pc_qty):
		bom = frappe.get_doc("BOM", bom_name)
		batch_qty = flt(bom.quantity) or 1

		for row in bom.items:
			row_qty_per_pc = flt(row.stock_qty) * per_pc_qty / batch_qty
			if row.bom_no:
				_walk(row.bom_no, row_qty_per_pc)
			else:
				rm_items.append(
					{
						"rm_used": row.item_code,
						"rm_rate_per_kg": get_last_purchase_rate(row.item_code),
						"gross_wt_per_pc": row_qty_per_pc,
					}
				)
			subcontract_row = get_subcontract_operation_row(row.item_code, company=company)
			if subcontract_row:
				operation_items.append(subcontract_row)

		for row in bom.scrap_items:
			scrap_wt_per_pc = flt(row.stock_qty) * per_pc_qty / batch_qty
			scrap_items.append(
				{
					"scrap_description": row.item_code,
					"scrap_rate_per_kg": get_last_sales_rate(row.item_code),
					"scrap_wt_per_pc": scrap_wt_per_pc,
				}
			)

		for row in bom.operations:
			# "Per Min / Pc" on this doctype is a PRODUCTION RATE (pieces made
			# per minute) — since Rate/Pc = Shift Rate per Min ÷ Per Min/Pc.
			# BOM Operation's own custom_batchsize field already holds this
			# rate directly (pieces/min for that operation+machine) and is
			# NOT scaled by the estimate's batch qty — it's an intrinsic
			# property of the operation, not a quantity that grows with how
			# many finished pieces we're costing. Only fall back to deriving
			# it from time_in_mins (a per-piece cycle time in minutes, so its
			# reciprocal is pieces/min) when Batch Size isn't filled in.
			if flt(row.custom_batchsize):
				time_per_pc_min = flt(row.custom_batchsize)
			else:
				cycle_time_per_pc_min = flt(row.time_in_mins) * per_pc_qty / batch_qty
				time_per_pc_min = 1 / cycle_time_per_pc_min if cycle_time_per_pc_min else 0
			workstation = row.workstation or first_workstation_from_csv(row.custom_workstations_csv)

			operation_row = {
				"operation": row.operation,
				"workstation": workstation,
				"time_per_pc_min": time_per_pc_min,
			}
			if workstation:
				operation_row["shift_rate_per_min"] = frappe.db.get_value(
					"Workstation", workstation, "custom_cost_per_min"
				)
				asset = frappe.db.get_value("Workstation", workstation, "custom_asset_name")
				operation_row["machine_name"] = (
					frappe.db.get_value("Asset", asset, "asset_name") if asset else None
				)
			operation_items.append(operation_row)

	_walk(bom_name, per_pc_qty)
	return {"rm_items": rm_items, "scrap_items": scrap_items, "operation_items": operation_items}


@frappe.whitelist()
def get_bom_explosion(bom, item=None, company=None):
	"""Stateless version of the BOM pull — callable before the Cost
	Estimation document is even saved, so the browser can populate RM/Scrap/
	Operations live as soon as an Item (and its default BOM) is picked, with
	no button and no save round-trip required."""
	if not bom:
		frappe.throw(_("BOM is required."))

	data = explode_bom_tree(bom, per_pc_qty=1, company=company)
	if item:
		# The finished item's own subcontract step (if any) is the very last
		# thing that happens to it, after everything the BOM tree produces.
		trailing = get_subcontract_operation_row(item, company=company)
		if trailing:
			data["operation_items"].append(trailing)
	return data


def get_top_level_item_for_subcontract_order(subcontracting_order):
	"""A Subcontracting Order is raised for an intermediate item (e.g. 200632,
	Case Hardened) — but the ordered Operations sequence with that step's
	position in it only exists on the Cost Estimation of the top-level
	sellable item (e.g. 300918), since Cost Estimation explodes one item's
	whole BOM tree into a single flat, ordered list. Trace back through the
	documents that created this demand to find that top-level item:
	Subcontracting Order → its Purchase Order → each PO Item's Production
	Plan → that plan's own item_code (the finished item actually being
	planned for). Returns None if the chain is broken anywhere (e.g. a
	manually created Subcontracting Order with no Production Plan behind it)."""
	po = frappe.db.get_value("Subcontracting Order", subcontracting_order, "purchase_order")
	if not po:
		return None

	production_plan = frappe.db.get_value(
		"Purchase Order Item", {"parent": po, "production_plan": ["is", "set"]}, "production_plan"
	)
	if not production_plan:
		return None

	return frappe.db.get_value("Production Plan Item", {"parent": production_plan}, "item_code")


@frappe.whitelist()
def get_subcontract_annexure_rate(item_code, company=None, subcontracting_order=None):
	"""Per-piece cost to show on a "Send to Subcontractor" Stock Entry row for
	`item_code` — the item being received back from the subcontractor (e.g.
	200632, Case Hardened), not the raw material physically sent out. Which
	operation this shipment represents is read off item_code's own default
	Subcontract row (Item Subcontracting Supplier, same place its rate lives).
	The cost is Net RM Cost/Pc + the Rate/Pc of every operation that comes
	BEFORE that operation in the latest submitted Cost Estimation of the
	TOP-LEVEL finished item this subcontract order was raised for (traced via
	get_top_level_item_for_subcontract_order) — i.e. everything already spent
	on this piece up to the point it's handed to this subcontractor. Returns
	None if item_code has no subcontract row, the top-level item can't be
	traced, or no submitted Cost Estimation exists for it."""
	subcontract_row = get_subcontract_operation_row(item_code, company=company)
	if not subcontract_row or not subcontract_row.get("operation"):
		return None
	target_operation = subcontract_row["operation"]

	top_level_item = None
	if subcontracting_order:
		top_level_item = get_top_level_item_for_subcontract_order(subcontracting_order)
	if not top_level_item:
		top_level_item = item_code

	ce_filters = {"item": top_level_item, "docstatus": 1}
	if company:
		ce_filters["company"] = company
	ce_name = frappe.db.get_value(
		"Cost Estimation", ce_filters, "name", order_by="estimation_date desc, creation desc"
	)
	if not ce_name:
		return None

	ce = frappe.get_doc("Cost Estimation", ce_name)

	cumulative = flt(ce.net_rm_cost_per_pc)
	for row in ce.operation_items:
		if row.operation == target_operation:
			break
		cumulative += flt(row.rate_per_pc)

	return {"rate": cumulative, "cost_estimation": ce_name, "operation": target_operation}


@frappe.whitelist()
def get_subcontract_po_rate(fg_item, company=None):
	"""Per-piece service rate to show on a subcontracting Purchase Order row
	for `fg_item` (the finished item coming back from the subcontractor, e.g.
	200632 for Case Hardening, 200633 for Plating) — just that one operation's
	own Rate/Pc, straight off the item's default Subcontract row (Item master
	→ Subcontracting Suppliers), the same rate Cost Estimation itself pulls in.
	Unlike the Stock Entry annexure rate, this is NOT cumulative — a
	subcontracting PO only ever pays for the single operation it's ordering.
	Returns None if fg_item has no subcontract row."""
	row = get_subcontract_operation_row(fg_item, company=company)
	if not row:
		return None
	return {"rate": flt(row["rate_per_pc"]), "operation": row["operation"]}


def _fmt(value):
	return f"₹{flt(value):,.3f}"


def _row(label, value, muted=False, is_total=False):
	classes = "ce-row"
	if muted:
		classes += " ce-row--muted"
	if is_total:
		classes += " ce-row--total"
	return f"""
		<div class="{classes}">
			<span class="ce-row__label">{label}</span>
			<span class="ce-row__value">{_fmt(value)}</span>
		</div>
	"""


def _details_row(summary_label, summary_value, child_rows_html, bold=False):
	classes = "ce-row ce-row--parent" + (" ce-row--bold" if bold else "")
	return f"""
		<details class="ce-node">
			<summary class="{classes}">
				<span class="ce-row__label"><span class="ce-caret">▸</span>{summary_label}</span>
				<span class="ce-row__value">{_fmt(summary_value)}</span>
			</summary>
			<div class="ce-node__children">
				{child_rows_html}
			</div>
		</details>
	"""


CE_SUMMARY_STYLE = """
	<style>
		.ce-summary-tree { width: 100%; font-variant-numeric: tabular-nums; font-size: 14px; }
		.ce-summary-tree .ce-card {
			border: 1px solid var(--border-color); border-radius: var(--border-radius, 8px);
			overflow: hidden; background: var(--fg-color, transparent);
		}
		.ce-summary-tree .ce-row {
			display: flex; align-items: center; justify-content: space-between;
			padding: 11px 20px; gap: 16px;
		}
		.ce-summary-tree .ce-row__label {
			color: var(--text-color); min-width: 0; overflow: hidden; text-overflow: ellipsis;
			white-space: nowrap; display: flex; align-items: center;
		}
		.ce-summary-tree .ce-row__value { color: var(--text-color); white-space: nowrap; font-weight: 500; flex-shrink: 0; }
		.ce-summary-tree .ce-row--muted .ce-row__label,
		.ce-summary-tree .ce-row--muted .ce-row__value { color: var(--text-muted); font-weight: 400; }
		.ce-summary-tree .ce-row--bold .ce-row__label,
		.ce-summary-tree .ce-row--bold .ce-row__value { font-weight: 600; }
		.ce-summary-tree .ce-row--total {
			background: var(--control-bg); font-weight: 600;
			border-top: 1px solid var(--border-color); border-bottom: 1px solid var(--border-color);
		}
		.ce-summary-tree .ce-row--total .ce-row__label,
		.ce-summary-tree .ce-row--total .ce-row__value { font-weight: 600; }
		.ce-summary-tree .ce-node:not(:last-child) { border-bottom: 1px solid var(--border-color); }
		.ce-summary-tree .ce-row--parent { cursor: pointer; list-style: none; }
		.ce-summary-tree .ce-row--parent::-webkit-details-marker { display: none; }
		.ce-summary-tree .ce-row--parent:hover { background: var(--control-bg); }
		.ce-summary-tree .ce-caret {
			display: inline-block; width: 14px; flex-shrink: 0; margin-right: 8px;
			color: var(--text-muted); font-size: 10px; transition: transform 0.15s ease;
		}
		.ce-summary-tree details[open] > summary .ce-caret { transform: rotate(90deg); }
		.ce-summary-tree .ce-node__children {
			margin: 0 20px 10px 34px; padding-left: 16px;
			border-left: 2px solid var(--border-color);
		}
		.ce-summary-tree .ce-node__children .ce-row { padding: 7px 10px; }
		.ce-summary-tree .ce-hero {
			margin-top: 16px; padding: 18px 24px; border-radius: var(--border-radius, 8px);
			background: var(--control-bg); border: 1px solid var(--border-color);
			display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px;
		}
		.ce-summary-tree .ce-hero__label {
			font-size: 12.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em;
		}
		.ce-summary-tree .ce-hero__value {
			font-size: 28px; font-weight: 700; color: var(--text-color);
		}
	</style>
"""


def build_summary_tree_html(doc):
	"""Nested, expandable (<details>/<summary>) breakdown of every cost line
	on the estimate — click a subtotal (Gross RM Cost, Operations Cost, etc.)
	to see exactly which item/operation rows it's made of and at what
	rate/qty, without cluttering the collapsed view."""
	rm_child_rows = "".join(
		_row(
			f"{r.rm_used or '—'}  ({flt(r.gross_wt_per_pc):.3f} kg × {flt(r.rm_rate_per_kg):.3f})",
			r.gross_rm_cost_per_pc,
			muted=True,
		)
		for r in doc.rm_items
	) or _row("No RM rows", 0, muted=True)

	scrap_child_rows = "".join(
		_row(
			f"{r.scrap_description or '—'}  ({flt(r.scrap_wt_per_pc):.3f} kg × {flt(r.scrap_rate_per_kg):.3f})",
			r.scrap_price_per_pc,
			muted=True,
		)
		for r in doc.scrap_items
	) or _row("No scrap rows", 0, muted=True)

	op_child_rows = "".join(
		_row(
			f"{r.operation or '—'} — {r.machine_name or r.workstation or 'no machine'}  "
			f"({flt(r.shift_rate_per_min):.3f} ÷ {flt(r.time_per_pc_min):.3f} pc/min)",
			r.rate_per_pc,
			muted=True,
		)
		for r in doc.operation_items
	) or _row("No operation rows", 0, muted=True)

	other_cost_rows = "".join(
		[
			_row(
				f"Inventory Carrying ({flt(doc.inventory_carrying_pct):.2f}%)",
				doc.inventory_carrying_cost,
				muted=True,
			),
			_row(
				f"Packing & Forwarding ({flt(doc.packing_forwarding_pct):.2f}%)",
				doc.packing_forwarding_cost,
				muted=True,
			),
			_row(f"Rejection ({flt(doc.rejection_pct):.2f}%)", doc.rejection_cost, muted=True),
		]
	)
	other_costs_total = (
		flt(doc.inventory_carrying_cost) + flt(doc.packing_forwarding_cost) + flt(doc.rejection_cost)
	)

	body = "".join(
		[
			_details_row("Gross RM Cost / Pc", doc.total_gross_rm_cost_per_pc, rm_child_rows),
			_details_row("Scrap Recovery / Pc", -flt(doc.total_scrap_price_per_pc), scrap_child_rows),
			_row("Net RM Cost / Pc", doc.net_rm_cost_per_pc, is_total=True),
			_details_row(
				"Total Labour (Operations) Cost / Pc",
				doc.total_labour_cost_per_pc,
				op_child_rows,
				bold=True,
			),
			_details_row("Other Costs / Pc", other_costs_total, other_cost_rows, bold=True),
			_row("Total Cost / Pc", doc.total_cost_per_pc, is_total=True),
			_row(
				"Profit Amount / Pc"
				+ (f" ({flt(doc.profit_pct):.2f}%)" if doc.profit_mode == "Percentage" else " (flat)"),
				doc.profit_amount,
				muted=True,
			),
			_row("Total Component Cost / Pc", doc.total_component_cost, is_total=True),
		]
	)

	return f"""
		{CE_SUMMARY_STYLE}
		<div class="ce-summary-tree">
			<div class="ce-card">
				{body}
			</div>
			<div class="ce-hero">
				<div class="ce-hero__label">Total Component Cost &times; Qty ({flt(doc.qty):.3f})</div>
				<div class="ce-hero__value">{_fmt(doc.total_component_cost_for_qty)}</div>
			</div>
		</div>
	"""


class CostEstimation(Document):
	def validate(self):
		# Only re-explode the BOM tree when the BOM field doesn't match what
		# it was last pulled from — i.e. the user picked a different BOM
		# since the last save. A brand-new record whose tables were already
		# populated by the live client-side fetch has last_pulled_bom set to
		# match, so this correctly does nothing and preserves any edits made
		# since. This is what replaces the old "Pull from BOM" button.
		if self.bom and self.bom != self.last_pulled_bom:
			self.apply_bom_explosion()

		self.calculate_rm_cost()
		self.calculate_operations_cost()
		self.calculate_other_costs()
		self.calculate_totals()
		self.set_summary_html()

	def apply_bom_explosion(self):
		data = explode_bom_tree(self.bom, per_pc_qty=1, company=self.company)
		if self.item:
			trailing = get_subcontract_operation_row(self.item, company=self.company)
			if trailing:
				data["operation_items"].append(trailing)

		self.rm_items = []
		for row in data["rm_items"]:
			self.append("rm_items", row)

		self.scrap_items = []
		for row in data["scrap_items"]:
			self.append("scrap_items", row)

		self.operation_items = []
		for row in data["operation_items"]:
			self.append("operation_items", row)

		self.last_pulled_bom = self.bom

	def calculate_rm_cost(self):
		total_gross_rm_cost = 0.0
		for row in self.rm_items:
			row.gross_rm_cost_per_pc = flt(row.gross_wt_per_pc) * flt(row.rm_rate_per_kg)
			total_gross_rm_cost += flt(row.gross_rm_cost_per_pc)
		self.total_gross_rm_cost_per_pc = total_gross_rm_cost

		total_scrap_price = 0.0
		for row in self.scrap_items:
			row.scrap_price_per_pc = flt(row.scrap_wt_per_pc) * flt(row.scrap_rate_per_kg)
			total_scrap_price += flt(row.scrap_price_per_pc)
		self.total_scrap_price_per_pc = total_scrap_price

		self.net_rm_cost_per_pc = self.total_gross_rm_cost_per_pc - self.total_scrap_price_per_pc

	def calculate_operations_cost(self):
		total_labour_cost = 0.0
		for row in self.operation_items:
			if row.workstation:
				if not row.shift_rate_per_min:
					row.shift_rate_per_min = frappe.db.get_value(
						"Workstation", row.workstation, "custom_cost_per_min"
					)
				if not row.machine_name:
					asset = frappe.db.get_value("Workstation", row.workstation, "custom_asset_name")
					row.machine_name = frappe.db.get_value("Asset", asset, "asset_name") if asset else None

				# Rate per Pc is always user-editable. Only auto-compute it here
				# when it's still empty (a fresh/BOM-pulled row) — once a value
				# is present, whether typed by hand or from an earlier
				# calculation, later saves leave it alone so a manual override
				# survives.
				if not row.rate_per_pc and flt(row.time_per_pc_min):
					row.rate_per_pc = math.ceil(flt(row.shift_rate_per_min) / flt(row.time_per_pc_min) * 100) / 100
			# else: no machine (e.g. subcontracted Plating) — rate_per_pc is typed directly, left as-is

			total_labour_cost += flt(row.rate_per_pc)

		self.total_labour_cost_per_pc = total_labour_cost

	def calculate_other_costs(self):
		base_for_pct = flt(self.net_rm_cost_per_pc) + flt(self.total_labour_cost_per_pc)

		rm_value_for_inventory = sum(
			flt(row.gross_wt_per_pc) * flt(row.rm_rate_per_kg) for row in self.rm_items
		)
		self.inventory_carrying_cost = rm_value_for_inventory * flt(self.inventory_carrying_pct) / 100
		self.packing_forwarding_cost = base_for_pct * flt(self.packing_forwarding_pct) / 100
		self.rejection_cost = base_for_pct * flt(self.rejection_pct) / 100

	def calculate_totals(self):
		base_for_pct = flt(self.net_rm_cost_per_pc) + flt(self.total_labour_cost_per_pc)

		self.total_cost_per_pc = (
			base_for_pct
			+ flt(self.inventory_carrying_cost)
			+ flt(self.packing_forwarding_cost)
			+ flt(self.rejection_cost)
		)

		if self.profit_mode == "Percentage":
			self.profit_amount = base_for_pct * flt(self.profit_pct) / 100

		self.total_component_cost = flt(self.total_cost_per_pc) + flt(self.profit_amount)
		self.total_component_cost_for_qty = self.total_component_cost * flt(self.qty)

	def set_summary_html(self):
		self.summary_html = build_summary_tree_html(self)
