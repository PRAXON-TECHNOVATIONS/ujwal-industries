# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

# FUTURE USE — currently hidden (2026-10-31).
# This doctype is not needed in the system right now, so all role permissions
# were removed from quotation_cost_estimation.json: only Administrator can
# open it and it does not appear for any other user. The code is kept as-is
# for a future quotation-costing flow (costing new parts that have no Item/BOM
# yet). To re-enable: add role permissions back in the JSON (previously System
# Manager, Manufacturing Manager, Manufacturing User) and run `bench migrate`.

import frappe
from frappe.model.document import Document
from frappe.utils import flt


def compute_rate_per_pc(shift_rate_per_min, time_per_pc_min):
	"""Rate/Pc = Shift Rate per Min ÷ Per Min/Pc — same formula as Cost
	Estimation, minus its tool-cavity and qty-multiplier adjustments (a
	quotation part has no BOM or tool yet)."""
	if not flt(time_per_pc_min):
		return 0
	return flt(shift_rate_per_min) / flt(time_per_pc_min)


class QuotationCostEstimation(Document):
	"""Cost Estimation for a part that doesn't exist in the system yet (an
	enquiry/quotation) — Part, RM and Scrap are typed in by hand instead of
	linked, and there's no BOM pull. Everything here is per piece; only the
	final total is multiplied by Quantity."""

	def validate(self):
		self.calculate_rm_cost()
		self.calculate_operations_cost()
		self.calculate_other_costs()
		self.calculate_totals()

	def calculate_rm_cost(self):
		for row in self.rm_items:
			row.gross_rm_cost_per_pc = flt(row.gross_wt_per_pc) * flt(row.rm_rate_per_kg)
		self.total_gross_rm_cost_per_pc = sum(flt(r.gross_rm_cost_per_pc) for r in self.rm_items)

		for row in self.scrap_items:
			row.scrap_price_per_pc = flt(row.scrap_wt_per_pc) * flt(row.scrap_rate_per_kg)
		self.total_scrap_price_per_pc = sum(flt(r.scrap_price_per_pc) for r in self.scrap_items)

		self.net_rm_cost_per_pc = self.total_gross_rm_cost_per_pc - self.total_scrap_price_per_pc

	def calculate_operations_cost(self):
		for row in self.operation_items:
			if row.workstation:
				# Client-side fetch doesn't run for API/server-side inserts.
				if not row.shift_rate_per_min:
					row.shift_rate_per_min = frappe.db.get_value(
						"Workstation", row.workstation, "custom_cost_per_min"
					)
				if not row.machine_name:
					asset = frappe.db.get_value("Workstation", row.workstation, "custom_asset_name")
					row.machine_name = frappe.db.get_value("Asset", asset, "asset_name") if asset else None
				# Only fill an empty Rate per Pc so a manual override survives.
				if not row.rate_per_pc and flt(row.time_per_pc_min):
					row.rate_per_pc = compute_rate_per_pc(row.shift_rate_per_min, row.time_per_pc_min)

		self.total_labour_cost_per_pc = sum(flt(r.rate_per_pc) for r in self.operation_items)

	def _base_for_pct(self):
		return flt(self.net_rm_cost_per_pc) + flt(self.total_labour_cost_per_pc)

	def calculate_other_costs(self):
		base_for_pct = self._base_for_pct()
		self.inventory_carrying_cost = (
			flt(self.total_gross_rm_cost_per_pc) * flt(self.inventory_carrying_pct) / 100
		)
		self.packing_forwarding_cost = base_for_pct * flt(self.packing_forwarding_pct) / 100
		self.rejection_cost = base_for_pct * flt(self.rejection_pct) / 100

	def calculate_totals(self):
		base_for_pct = self._base_for_pct()

		self.total_cost_per_pc = (
			base_for_pct
			+ flt(self.inventory_carrying_cost)
			+ flt(self.packing_forwarding_cost)
			+ flt(self.rejection_cost)
		)

		if self.profit_mode == "Percentage":
			self.profit_amount = base_for_pct * flt(self.profit_pct) / 100

		self.total_component_cost = flt(self.total_cost_per_pc) + flt(self.profit_amount)
		self.total_component_cost_for_qty = flt(self.total_component_cost) * (flt(self.qty) or 1)
