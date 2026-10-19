"""Set Production Plan custom_parallel_planning from its Bulk Pre Production Plan's planning mode.

BPP used to hard-code the flag to 1 on every PP it created, even for Sequential plans.
The flag is now always visible on the PP form to show how it was planned, so fix old PPs:
Sequential → 0, Parallel / Consolidated → 1. PPs not made from a BPP are left alone.
"""

import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabProduction Plan` pp
		INNER JOIN `tabBulk Pre Production Plan` bpp
			ON bpp.name = pp.custom_bulk_pre_production_plan
		SET pp.custom_parallel_planning =
			IF(COALESCE(NULLIF(bpp.custom_planning_mode, ''), 'Sequential') = 'Sequential', 0, 1)
		"""
	)
