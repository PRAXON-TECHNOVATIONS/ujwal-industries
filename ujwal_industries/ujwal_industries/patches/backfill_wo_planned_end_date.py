"""Backfill Work Order planned_end_date from the Production Plan that created it.

Draft Work Orders never get a planned_end_date (ERPNext only computes it on submit).
The Production Plan already holds the planned end date per assembly / sub-assembly row,
so copy it onto the Work Order so the Store Display (and the WO form) show the end date.
"""

import frappe


def execute():
	work_orders = frappe.db.sql(
		"""
		SELECT
			wo.name,
			COALESCE(ppsa.custom_schedule_end_date, ppi.custom_planned_end_date) AS end_date
		FROM `tabWork Order` wo
		LEFT JOIN `tabProduction Plan Item` ppi
			ON ppi.name = wo.production_plan_item
		LEFT JOIN `tabProduction Plan Sub Assembly Item` ppsa
			ON ppsa.name = wo.production_plan_sub_assembly_item
		WHERE
			wo.planned_end_date IS NULL
			AND COALESCE(ppsa.custom_schedule_end_date, ppi.custom_planned_end_date) IS NOT NULL
		""",
		as_dict=True,
	)

	for wo in work_orders:
		frappe.db.set_value(
			"Work Order",
			wo.name,
			"planned_end_date",
			wo.end_date,
			update_modified=False,
		)

	frappe.db.commit()

	if work_orders:
		frappe.logger().info(
			f"backfill_wo_planned_end_date: set planned_end_date on {len(work_orders)} Work Order(s)"
		)
