# Copyright (c) 2026, Ujjwal Aggrawal and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CostEstimation(Document):
	def before_insert(self):
		self.populate_from_bom()

	def validate(self):
		self.resum_totals()

	@frappe.whitelist()
	def recalculate(self):
		"""Wipe and rebuild every row fresh from the BOM tree and current
		masters (Designation Cost Rate / Overhead Charge Rate). Discards any
		manual edits made to existing rows - user must call this explicitly."""
		self.populate_from_bom()
		self.resum_totals()
		self.save()

	def populate_from_bom(self):
		self.rm_items = []
		self.scrap_items = []
		self.machine_items = []
		self.labour_items = []
		self.overhead_items = []

		self.explode_bom(self.bom, exploded_qty=flt(self.qty))

	def resum_totals(self):
		"""Recompute header totals from whatever rows currently exist in the
		child tables - does NOT touch the rows themselves, so manual edits to
		individual rows (rate, qty, hours, etc.) are respected on every save."""
		self.total_rm_cost = sum(flt(r.amount) for r in self.rm_items)
		self.scrap_recovery = sum(flt(r.amount) for r in self.scrap_items)
		self.net_rm_cost = self.total_rm_cost - self.scrap_recovery

		top_level_machine = [r for r in self.machine_items if r.source_bom == self.bom]
		top_level_labour = [r for r in self.labour_items if r.source_bom == self.bom]
		top_level_overhead = [r for r in self.overhead_items if r.source_bom == self.bom]

		self.total_machine_cost = sum(flt(r.machine_cost) for r in top_level_machine)
		self.total_labour_cost = sum(flt(r.labour_cost) for r in top_level_labour)
		self.total_overhead_cost = sum(flt(r.applied_amount) for r in top_level_overhead)

		self.tree_total_machine_cost = sum(flt(r.machine_cost) for r in self.machine_items)
		self.tree_total_labour_cost = sum(flt(r.labour_cost) for r in self.labour_items)
		self.tree_total_overhead_cost = sum(flt(r.applied_amount) for r in self.overhead_items)

		self.subtotal_cost = self.net_rm_cost + self.total_machine_cost + self.total_labour_cost
		self.total_estimated_cost = self.subtotal_cost + self.total_overhead_cost
		self.cost_per_unit = self.total_estimated_cost / self.qty if self.qty else 0

	def explode_bom(self, bom_name, exploded_qty):
		"""Recursively walk this BOM and every sub-assembly BOM beneath it,
		appending flattened RM/Scrap/Machine/Labour/Overhead rows tagged with
		their source_bom/source_item, and returning this level's own totals.

		`exploded_qty` is how many finished units of *this* BOM's item are
		needed for the top-level estimate (e.g. if the top item needs 100 pcs,
		and each needs 1 of a sub-assembly, the sub-assembly's exploded_qty is
		also 100). Every cost figure returned/appended is already scaled to
		this exploded_qty, so the caller can just sum them.

		Overhead is applied once per BOM level (on that level's own RM /
		subtotal), then rolled up - so overhead compounds through the tree
		rather than being calculated once at the very end.
		"""
		bom = frappe.get_doc("BOM", bom_name)
		batches = exploded_qty / bom.quantity if bom.quantity else 0

		rm_cost = 0.0
		scrap_cost = 0.0
		machine_cost = 0.0
		labour_cost = 0.0

		for row in bom.items:
			row_qty = flt(row.stock_qty) * batches
			if row.bom_no:
				# A sub-assembly is a consumed input at this level: its fully-loaded
				# cost (own RM + machine + labour + overhead) stands in as this
				# row's "RM cost" here. Machine/labour/overhead display rows from
				# the sub-level are still appended (via the recursive call) so the
				# full tree is visible, but they are NOT added again into this
				# level's own machine_cost/labour_cost totals - that would double
				# count them, since they're already inside sub_result.total_cost.
				sub_result = self.explode_bom(row.bom_no, exploded_qty=row_qty)
				rm_cost_this_row = sub_result.total_cost
				rm_cost += rm_cost_this_row
				self.append(
					"rm_items",
					{
						"item_code": row.item_code,
						"source_bom": bom_name,
						"source_item": bom.item,
						"qty": row_qty,
						"rate": rm_cost_this_row / row_qty if row_qty else 0,
						"amount": rm_cost_this_row,
					},
				)
			else:
				rm_cost_this_row = row_qty * flt(row.rate)
				rm_cost += rm_cost_this_row
				self.append(
					"rm_items",
					{
						"item_code": row.item_code,
						"source_bom": bom_name,
						"source_item": bom.item,
						"qty": row_qty,
						"rate": row.rate,
						"amount": rm_cost_this_row,
					},
				)

		for scrap_row in bom.scrap_items:
			scrap_qty = flt(scrap_row.stock_qty) * batches
			scrap_amount = scrap_qty * flt(scrap_row.rate)
			scrap_cost += scrap_amount
			self.append(
				"scrap_items",
				{
					"item_code": scrap_row.item_code,
					"source_bom": bom_name,
					"source_item": bom.item,
					"qty": scrap_qty,
					"rate": scrap_row.rate,
					"amount": scrap_amount,
				},
			)

		for op_row in bom.operations:
			op_cost = flt(op_row.operating_cost) * batches
			machine_cost += op_cost
			self.append(
				"machine_items",
				{
					"operation": op_row.operation,
					"workstation": op_row.workstation,
					"source_bom": bom_name,
					"source_item": bom.item,
					"time_in_mins": flt(op_row.time_in_mins) * batches,
					"hour_rate": op_row.hour_rate,
					"machine_cost": op_cost,
				},
			)

			labour_rows = frappe.get_all(
				"BOM Operation Labour Detail",
				filters={"parent": op_row.name, "parenttype": "BOM Operation"},
				fields=["designation", "labour_hours", "head_count"],
				order_by="idx",
			)
			for labour_row in labour_rows:
				hourly_rate = get_designation_hourly_rate(
					labour_row.designation, self.company, self.estimation_date
				)
				head_count = flt(labour_row.head_count or 1)
				this_labour_cost = flt(labour_row.labour_hours) * head_count * hourly_rate * batches
				labour_cost += this_labour_cost
				self.append(
					"labour_items",
					{
						"operation": op_row.operation,
						"designation": labour_row.designation,
						"source_bom": bom_name,
						"source_item": bom.item,
						"labour_hours": flt(labour_row.labour_hours) * batches,
						"head_count": head_count,
						"hourly_rate": hourly_rate,
						"labour_cost": this_labour_cost,
					},
				)

		net_rm_cost = rm_cost - scrap_cost
		subtotal = net_rm_cost + machine_cost + labour_cost
		overhead_cost = self.apply_overheads(bom_name, bom.item, net_rm_cost, subtotal, exploded_qty)
		total_cost = subtotal + overhead_cost

		return frappe._dict(
			rm_cost=rm_cost,
			scrap_cost=scrap_cost,
			machine_cost=machine_cost,
			labour_cost=labour_cost,
			overhead_cost=overhead_cost,
			total_cost=total_cost,
		)

	def apply_overheads(self, bom_name, item_code, net_rm_cost, subtotal, exploded_qty):
		overhead_rules = frappe.get_all(
			"Overhead Charge Rate",
			filters={
				"company": self.company,
				"is_active": 1,
				"effective_from": ("<=", self.estimation_date),
			},
			fields=["name", "charge_name", "basis", "rate", "effective_from"],
			order_by="effective_from desc",
		)

		seen_charges = set()
		total_overhead_cost = 0.0
		for rule in overhead_rules:
			if rule.charge_name in seen_charges:
				continue
			seen_charges.add(rule.charge_name)

			if rule.basis == "% of RM Cost":
				applied_amount = net_rm_cost * flt(rule.rate) / 100
			elif rule.basis == "% of Total Cost":
				applied_amount = subtotal * flt(rule.rate) / 100
			elif rule.basis == "Flat per Unit":
				applied_amount = flt(rule.rate) * exploded_qty
			else:
				applied_amount = 0

			total_overhead_cost += applied_amount
			self.append(
				"overhead_items",
				{
					"charge_name": rule.charge_name,
					"source_bom": bom_name,
					"source_item": item_code,
					"basis": rule.basis,
					"rate": rule.rate,
					"applied_amount": applied_amount,
				},
			)

		return total_overhead_cost


def get_designation_hourly_rate(designation, company, on_date):
	rate = frappe.get_all(
		"Designation Cost Rate",
		filters={
			"designation": designation,
			"company": company,
			"is_active": 1,
			"effective_from": ("<=", on_date),
		},
		fields=["hourly_rate"],
		order_by="effective_from desc",
		limit=1,
	)
	if not rate:
		frappe.throw(
			_("No active Designation Cost Rate found for {0} in {1} on or before {2}").format(
				designation, company, on_date
			)
		)
	return flt(rate[0].hourly_rate)
