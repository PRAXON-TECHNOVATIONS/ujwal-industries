# Copyright (c) 2026, Ujwal Industries
# License: MIT
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""
Production Plan overrides — thin entry point.

All logic lives in the pp_* sub-modules. This file re-exports every public symbol so that:
  - hooks.py paths (ujwal_industries...overrides.production_plan.*) remain valid
  - JavaScript frappe.call() paths remain valid
  - Any other code importing from this module continues to work

Sub-modules:
  pp_utils.py     — shared utility / helper functions
  pp_fg_dates.py  — FG (po_items) date calculations
  pp_sfg_dates.py — SFG (sub_assembly_items) date calculations
  pp_mr_dates.py  — MR (mr_items) date management + propagation
  pp_cascade.py   — client-triggered cascade / propagation
"""

# Use "name as name" so Pyright treats each import as an intentional public re-export.

from .pp_utils import get_subcontract_lead_time as get_subcontract_lead_time
from .pp_utils import get_production_time as get_production_time
from .pp_utils import get_item_default_warehouse as get_item_default_warehouse
from .pp_utils import get_supplier_lead_time as get_supplier_lead_time
from .pp_utils import calculate_production_time_from_bom as calculate_production_time_from_bom

from .pp_fg_dates import validate_planned_start_dates as validate_planned_start_dates
from .pp_fg_dates import master_set_fg_dates_by_type as master_set_fg_dates_by_type
from .pp_fg_dates import get_item_suppliers_query as get_item_suppliers_query
from .pp_fg_dates import get_subcontract_updates_client as get_subcontract_updates_client
from .pp_fg_dates import set_planned_start_dates as set_planned_start_dates

from .pp_sfg_dates import onload_production_plan as onload_production_plan
from .pp_sfg_dates import refresh_original_mr_dates as refresh_original_mr_dates
from .pp_sfg_dates import refresh_original_subassembly_dates as refresh_original_subassembly_dates
from .pp_sfg_dates import calculate_inhouse_schedule_dates as calculate_inhouse_schedule_dates
from .pp_sfg_dates import calculate_fg_date_from_subassembly as calculate_fg_date_from_subassembly
from .pp_sfg_dates import set_subcontracting_suppliers as set_subcontracting_suppliers
from .pp_sfg_dates import calculate_fg_dates_from_subassembly as calculate_fg_dates_from_subassembly

from .pp_mr_dates import adjust_mr_items_and_propagate as adjust_mr_items_and_propagate
from .pp_mr_dates import calculate_mr_item_dates as calculate_mr_item_dates

from .pp_cascade import cascade_sfg_date_change as cascade_sfg_date_change
from .pp_cascade import calculate_sfg_fg_dates_from_mr_items as calculate_sfg_fg_dates_from_mr_items

from .tool_limit import validate_tool_limit as validate_tool_limit
from .pp_mr_dates import set_item_type_in_production_plan as set_item_type_in_production_plan


def on_trash_production_plan(doc, method=None):
	"""Reset custom_pp_created on the Bulk Pre Production Plan when a Production Plan is deleted."""
	bulk_pp_name = getattr(doc, "custom_bulk_pre_production_plan", None)
	if not bulk_pp_name:
		return

	so_names = [row.sales_order for row in (doc.get("sales_orders") or []) if getattr(row, "sales_order", None)]
	if not so_names:
		return

	try:
		import frappe
		bulk_pp = frappe.get_doc("Bulk Pre Production Plan", bulk_pp_name)
		changed = False
		for row in bulk_pp.get("sales_orders") or []:
			if row.sales_order in so_names and getattr(row, "custom_pp_created", 0):
				row.custom_pp_created = 0
				changed = True
		if changed:
			bulk_pp.flags.ignore_mandatory = True
			bulk_pp.save()
	except Exception:
		import frappe
		frappe.log_error(frappe.get_traceback(), "on_trash_production_plan: failed to reset custom_pp_created")