# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

import math

import frappe
from frappe.model.document import Document
from frappe.utils import flt


class CostEstimation(Document):
	def validate(self):
		self.calculate_rm_cost()
		self.calculate_operations_cost()
		self.calculate_other_costs()
		self.calculate_totals()
		self.set_summary_html()

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

				row.rate_per_pc = math.ceil(
					flt(row.shift_rate_per_min) / flt(row.time_per_pc_min) * 100
				) / 100
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
		rows = [
			("Total Gross RM Cost / Pc", self.total_gross_rm_cost_per_pc),
			("Total Scrap Price / Pc", -flt(self.total_scrap_price_per_pc)),
			("Net RM Cost / Pc", self.net_rm_cost_per_pc, True),
			("Total Labour (Operations) Cost / Pc", self.total_labour_cost_per_pc, True),
			("Inventory Carrying Cost / Pc", self.inventory_carrying_cost),
			("Packing & Forwarding Cost / Pc", self.packing_forwarding_cost),
			("Rejection Cost / Pc", self.rejection_cost),
			("Total Cost / Pc", self.total_cost_per_pc, True),
			("Profit Amount / Pc", self.profit_amount),
			("Total Component Cost / Pc", self.total_component_cost, True),
			(f"Total Component Cost (Qty: {flt(self.qty)})", self.total_component_cost_for_qty, True),
		]

		row_html = ""
		for row in rows:
			label, value = row[0], row[1]
			is_total = len(row) > 2 and row[2]
			style = (
				"font-weight:600;border-top:1px solid var(--border-color);"
				if is_total
				else "color:var(--text-muted);"
			)
			row_html += f"""
				<tr style="{style}">
					<td style="padding:6px 12px;">{label}</td>
					<td style="padding:6px 12px;text-align:right;">{flt(value):.3f}</td>
				</tr>
			"""

		self.summary_html = f"""
			<table style="width:100%;border-collapse:collapse;max-width:480px;">
				{row_html}
			</table>
		"""
