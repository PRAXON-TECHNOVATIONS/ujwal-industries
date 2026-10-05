"""Patches for standard ERPNext script reports that query Purchase Order with raw SQL
and so bypass permission_query_conditions.

Applied from before_request / before_job because hooks.py is served from cache and
an import-time patch there is not guaranteed to run in every worker.
"""

from erpnext.buying.report.purchase_order_analysis import purchase_order_analysis

from ujwal_industries.ujwal_industries.overrides.purchase_order import filter_rows_by_po_access


def _patch_purchase_order_analysis():
	if getattr(purchase_order_analysis.get_data, "_ujwal_patched", False):
		return

	original_get_data = purchase_order_analysis.get_data

	def get_data(filters):
		return filter_rows_by_po_access(original_get_data(filters))

	get_data._ujwal_patched = True
	purchase_order_analysis.get_data = get_data


def apply(*args, **kwargs):
	_patch_purchase_order_analysis()
