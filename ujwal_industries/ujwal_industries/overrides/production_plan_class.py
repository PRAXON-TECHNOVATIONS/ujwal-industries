# Copyright (c) 2026, Ujwal Industries
# License: MIT
# Override Production Plan class to handle FG subcontracting

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.manufacturing.doctype.production_plan.production_plan import ProductionPlan


class CustomProductionPlan(ProductionPlan):
    """
    Extended Production Plan class that handles FG subcontracting.

    When FG items have custom_manufacturing_type == "Subcontract",
    create a Purchase Order instead of a Work Order.
    """

    @frappe.whitelist()
    def make_work_order(self):
        """
        Override make_work_order to also handle FG subcontracting.
        """
        from erpnext.manufacturing.doctype.work_order.work_order import get_default_warehouse

        wo_list, po_list = [], []
        subcontracted_po = {}  # supplier -> list of items
        default_warehouses = get_default_warehouse()

        # Handle FG items - split between Work Orders and Subcontract POs
        self.make_work_order_for_finished_goods_with_subcontract(wo_list, subcontracted_po, default_warehouses)

        # Handle sub-assembly items (original logic)
        self.make_work_order_for_subassembly_items(wo_list, subcontracted_po, default_warehouses)

        # Create Purchase Orders for all subcontracted items (both FG and SFG)
        self.make_subcontracted_purchase_order_with_fg(subcontracted_po, po_list)

        self.show_list_created_message("Work Order", wo_list)
        self.show_list_created_message("Purchase Order", po_list)

    def make_work_order_for_finished_goods_with_subcontract(self, wo_list, subcontracted_po, default_warehouses):
        """
        Handle FG items - create Work Orders for In House, collect Subcontract items for PO.
        """
        from erpnext.manufacturing.doctype.production_plan.production_plan import set_default_warehouses

        items_data = self.get_production_items()

        for _key, item in items_data.items():
            # Check if this FG item is marked for subcontracting
            fg_row = None
            for po_item in self.po_items:
                if po_item.item_code == item.get("item_code"):
                    fg_row = po_item
                    break

            if fg_row and fg_row.get("custom_manufacturing_type") == "Subcontract":
                # This is a subcontract FG item - add to PO list
                supplier = fg_row.get("custom_supplier")
                if supplier:
                    subcontracted_po.setdefault(supplier, []).append({
                        "row": fg_row,
                        "item_data": item,
                        "is_fg": True  # Flag to identify FG items
                    })
                else:
                    frappe.msgprint(
                        _("FG Item {0} is marked for Subcontract but has no supplier set. Skipping.").format(
                            item.get("item_code")
                        )
                    )
                continue

            # Regular In House FG item - create Work Order
            if self.sub_assembly_items:
                item["use_multi_level_bom"] = 0

            set_default_warehouses(item, default_warehouses)
            work_order = self.create_work_order(item)
            if work_order:
                wo_list.append(work_order)

    def make_subcontracted_purchase_order_with_fg(self, subcontracted_po, purchase_orders):
        """
        Create Purchase Orders for subcontracted items (both FG and SFG).
        Uses old subcontracting flow for simplicity (item_code = the actual item).
        """
        if not subcontracted_po:
            return

        for supplier, items_list in subcontracted_po.items():
            po = frappe.new_doc("Purchase Order")
            po.company = self.company
            po.supplier = supplier
            po.is_subcontracted = 1
            po.is_old_subcontracting_flow = 1  # Use old flow - item_code is the actual item

            # Get schedule date from first item
            first_item = items_list[0]
            is_first_fg = isinstance(first_item, dict) and first_item.get("is_fg")
            if is_first_fg:
                # FG item
                fg_row = first_item["row"]
                po.schedule_date = getdate(fg_row.planned_start_date) if fg_row.planned_start_date else nowdate()
            else:
                # SFG item (original behavior - first_item is a Document object)
                po.schedule_date = getdate(first_item.schedule_date) if first_item.schedule_date else nowdate()

            for item_info in items_list:
                # Check if this is an FG item (dict with is_fg flag) or SFG item (Document object)
                is_fg_item = isinstance(item_info, dict) and item_info.get("is_fg")

                if is_fg_item:
                    # Handle FG subcontract item (old flow)
                    fg_row = item_info["row"]
                    item_data = item_info["item_data"]

                    # Calculate qty to order
                    qty_to_order = flt(fg_row.planned_qty) - flt(fg_row.ordered_qty)
                    if qty_to_order <= 0:
                        continue

                    # Old subcontracting flow - item_code is the actual item
                    po_data = {
                        "item_code": fg_row.item_code,  # The actual FG item
                        "warehouse": fg_row.warehouse,
                        "production_plan_item": fg_row.name,
                        "bom": fg_row.bom_no,
                        "production_plan": self.name,
                        "schedule_date": fg_row.planned_start_date,
                        "qty": qty_to_order,
                        "description": fg_row.description or item_data.get("description", ""),
                        "include_exploded_items": 1,  # Include BOM items for raw material tracking
                    }

                    po.append("items", po_data)
                else:
                    # Handle SFG subcontract item (original behavior - item_info is a Document object)
                    row = item_info

                    # For SFG items, also use old flow
                    po_data = {
                        "item_code": row.production_item,  # The actual SFG item
                        "warehouse": row.fg_warehouse,
                        "production_plan_sub_assembly_item": row.name,
                        "bom": row.bom_no,
                        "production_plan": self.name,
                        "schedule_date": row.schedule_date,
                        "qty": row.qty,
                        "description": row.description if row.get("description") else "",
                        "include_exploded_items": 1,
                    }

                    if row.get("production_plan_item"):
                        po_data["production_plan_item"] = row.production_plan_item

                    po.append("items", po_data)

            if not po.items:
                continue

            po.set_missing_values()

            try:
                po.flags.ignore_permissions = True
                po.flags.ignore_mandatory = True
                po.insert()
                po.submit()
                purchase_orders.append(po.name)
            except Exception as e:
                frappe.log_error(
                    message=str(e),
                    title=f"Error creating Purchase Order for supplier {supplier}"
                )
                frappe.msgprint(
                    _("Error creating Purchase Order for supplier {0}: {1}").format(supplier, str(e))
                )
