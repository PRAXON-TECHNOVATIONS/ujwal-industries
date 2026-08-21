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
		self.calculate_rm_cost()
		self.calculate_operations_cost()
		self.calculate_other_costs()
		self.calculate_totals()
		self.set_summary_html()

	@frappe.whitelist()
	def pull_from_bom(self):
		"""Pre-fill RM/Scrap/Operations from the selected BOM, recursively
		exploding any sub-assembly (a BOM item that itself has a `bom_no`) so
		every raw material, scrap line and operation in the whole tree shows
		up as its own row — not just the top level. Overwrites whatever is
		currently in those three tables — the caller is expected to confirm
		with the user first, since this discards any manual edits already
		made. Every pulled row stays fully editable afterwards; this is a
		one-time import, not a live link to the BOM."""
		if not self.bom:
			frappe.throw(_("Select a BOM first."))

		self.rm_items = []
		self.scrap_items = []
		self.operation_items = []

		self.explode_bom(self.bom, per_pc_qty=1)

		# Persist immediately (this also runs validate(), which fills in
		# rate_per_pc, totals and the summary) so the browser can reload the
		# doc and show real computed numbers right after the pull, instead
		# of the pulled rows sitting at their zero-value defaults until the
		# user manually saves.
		self.save()

	def explode_bom(self, bom_name, per_pc_qty):
		"""Walk this BOM and every sub-assembly BOM beneath it, appending
		flattened RM/Scrap/Operation rows scaled to `per_pc_qty` — how many
		units of *this* BOM's item are needed per one finished piece of the
		top-level item."""
		bom = frappe.get_doc("BOM", bom_name)
		batch_qty = flt(bom.quantity) or 1

		for row in bom.items:
			row_qty_per_pc = flt(row.stock_qty) * per_pc_qty / batch_qty
			if row.bom_no:
				self.explode_bom(row.bom_no, row_qty_per_pc)
			else:
				self.append(
					"rm_items",
					{
						"rm_used": row.item_code,
						"rm_rate_per_kg": get_last_purchase_rate(row.item_code),
						"gross_wt_per_pc": row_qty_per_pc,
					},
				)

		for row in bom.scrap_items:
			scrap_wt_per_pc = flt(row.stock_qty) * per_pc_qty / batch_qty
			self.append(
				"scrap_items",
				{
					"scrap_description": row.item_code,
					"scrap_rate_per_kg": get_last_sales_rate(row.item_code),
					"scrap_wt_per_pc": scrap_wt_per_pc,
				},
			)

		for row in bom.operations:
			# BOM Operation's time_in_mins is a per-piece CYCLE TIME (minutes to
			# make one piece), scaled down from the batch. "Per Min / Pc" on
			# this doctype is its reciprocal — a PRODUCTION RATE (pieces made
			# per minute) — since Rate/Pc = Shift Rate per Min ÷ Per Min/Pc.
			cycle_time_per_pc_min = flt(row.time_in_mins) * per_pc_qty / batch_qty
			time_per_pc_min = 1 / cycle_time_per_pc_min if cycle_time_per_pc_min else 0
			workstation = row.workstation or self.first_workstation_from_csv(row.custom_workstations_csv)

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
			self.append("operation_items", operation_row)

	@staticmethod
	def first_workstation_from_csv(csv_value):
		"""BOM Operation can list several interchangeable machines in
		custom_workstations_csv (e.g. 'UI/MC/94,UI/MC/95,...') when the
		standard single workstation field is left empty. Default to the
		first one listed — the pulled row stays editable if a different
		machine should be used for this estimate."""
		if not csv_value:
			return None
		return csv_value.split(",")[0].strip()

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
