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
		self.calculate_totals()

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
			if not row.shift_rate_per_min and row.workstation:
				row.shift_rate_per_min = frappe.db.get_value(
					"Workstation", row.workstation, "custom_cost_per_min"
				)
			if not row.machine_name and row.workstation:
				asset = frappe.db.get_value("Workstation", row.workstation, "custom_asset_name")
				row.machine_name = frappe.db.get_value("Asset", asset, "asset_name") if asset else None

			row.rate_per_pc = math.ceil(
				flt(row.time_per_pc_min) * flt(row.shift_rate_per_min) * 100
			) / 100
			total_labour_cost += flt(row.rate_per_pc)

		self.total_labour_cost_per_pc = total_labour_cost

	def calculate_totals(self):
		self.total_cost_per_pc = flt(self.net_rm_cost_per_pc) + flt(self.total_labour_cost_per_pc)
