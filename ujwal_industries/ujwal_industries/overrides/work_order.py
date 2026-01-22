# from __future__ import annotations
# import frappe
# from frappe import _
# from frappe.utils import flt

# def validate_finish_qty(doc) -> None:
#     """
#     Server-side validation for Finish quantity.
#     Validates input quantity against remaining ± item tolerance.
#     """
#     # Check if custom finish quantity is set
#     input_qty = getattr(doc, "custom_finish_qty", None)
#     if input_qty is None:
#         return  # Not a Finish operation, skip

#     # Work Order details
#     production_item = doc.production_item
#     qty_to_manufacture = flt(doc.qty or 0)
#     produced_qty = flt(doc.produced_qty or 0)
#     remaining_qty = qty_to_manufacture - produced_qty
#     remaining_qty = max(0.0, remaining_qty)

#     # Fetch tolerance % from Item Master
#     tolerance_pct = flt(frappe.db.get_value("Item", production_item, "custom_tolerance_") or 0.0)

#     tolerance_qty = remaining_qty * (tolerance_pct / 100)
#     min_qty = max(0.0, remaining_qty - tolerance_qty)
#     max_qty = remaining_qty + tolerance_qty

#     input_qty = flt(input_qty)
#     if input_qty < min_qty or input_qty > max_qty:
#         frappe.throw(
#             _("Finish quantity {0} is outside allowed range {1} to {2} "
#               "(Remaining: {3}, Tolerance: {4}%) for item {5}")
#             .format(input_qty, min_qty, max_qty, remaining_qty, tolerance_pct, production_item)
#         )
