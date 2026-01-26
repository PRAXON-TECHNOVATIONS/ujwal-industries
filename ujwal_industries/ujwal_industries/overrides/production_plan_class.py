# Copyright (c) 2026, Ujwal Industries
# License: MIT
# Override Production Plan class to handle FG subcontracting

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.manufacturing.doctype.production_plan.production_plan import (
    ProductionPlan,
    set_default_warehouses,
)


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
        Same pattern as ERPNext but passes subcontracted_po to FG method.
        """
        from erpnext.manufacturing.doctype.work_order.work_order import get_default_warehouse

        wo_list, po_list = [], []
        subcontracted_po = {}
        default_warehouses = get_default_warehouse()

        # Modified: pass subcontracted_po to FG method
        self.make_work_order_for_finished_goods(wo_list, subcontracted_po, default_warehouses)
        self.make_work_order_for_subassembly_items(wo_list, subcontracted_po, default_warehouses)
        self.make_subcontracted_purchase_order(subcontracted_po, po_list)
        self.show_list_created_message("Work Order", wo_list)
        self.show_list_created_message("Purchase Order", po_list)

    def make_work_order_for_finished_goods(self, wo_list, subcontracted_po, default_warehouses):
        """
        Override to handle FG subcontracting.
        If FG has custom_manufacturing_type == "Subcontract", add to subcontracted_po instead.
        """
        items_data = self.get_production_items()

        for _key, item in items_data.items():
            # Check if this FG item is marked for subcontracting
            # Note: get_production_items() returns 'production_item', not 'item_code'
            item_code = item.get("production_item")
            fg_row = None
            for po_item in self.po_items:
                if po_item.item_code == item_code:
                    fg_row = po_item
                    break

            if fg_row and fg_row.get("custom_manufacturing_type") == "Subcontract":
                # This is a subcontract FG item - add to subcontracted_po
                supplier = fg_row.get("custom_supplier")
                if supplier:
                    # Create a mock row object similar to sub_assembly_items structure
                    subcontracted_po.setdefault(supplier, []).append({
                        "is_fg": True,
                        "production_item": fg_row.item_code,
                        "fg_warehouse": fg_row.warehouse,
                        "name": fg_row.name,
                        "bom_no": fg_row.bom_no,
                        "qty": flt(fg_row.planned_qty) - flt(fg_row.ordered_qty),
                        "schedule_date": fg_row.planned_start_date,
                        "description": fg_row.description or item.get("description", ""),
                        "production_plan_item": fg_row.name,
                    })
                else:
                    frappe.msgprint(
                        _("FG Item {0} is marked for Subcontract but has no supplier. Skipping.").format(
                            item_code
                        )
                    )
                continue

            # Regular In House FG item - create Work Order (original logic)
            if self.sub_assembly_items:
                item["use_multi_level_bom"] = 0

            set_default_warehouses(item, default_warehouses)
            work_order = self.create_work_order(item)
            if work_order:
                wo_list.append(work_order)

    def make_subcontracted_purchase_order(self, subcontracted_po, purchase_orders):
        """
        Override to handle both FG and SFG subcontract items.
        """
        if not subcontracted_po:
            return

        for supplier, po_list in subcontracted_po.items():
            po = frappe.new_doc("Purchase Order")
            po.company = self.company
            po.supplier = supplier
            po.is_subcontracted = 1

            # Get schedule date from first item
            first_item = po_list[0]
            if isinstance(first_item, dict):
                po.schedule_date = getdate(first_item.get("schedule_date")) if first_item.get("schedule_date") else nowdate()
            else:
                po.schedule_date = getdate(first_item.schedule_date) if first_item.schedule_date else nowdate()

            for row in po_list:
                # Check if this is an FG item (dict) or SFG item (Document object)
                if isinstance(row, dict):
                    # FG subcontract item
                    if row.get("qty", 0) <= 0:
                        continue

                    po_data = {
                        "fg_item": row.get("production_item"),
                        "warehouse": row.get("fg_warehouse"),
                        "production_plan_item": row.get("production_plan_item"),
                        "bom": row.get("bom_no"),
                        "production_plan": self.name,
                        "fg_item_qty": row.get("qty"),
                        "schedule_date": row.get("schedule_date"),
                        "qty": row.get("qty"),
                        "description": row.get("description", ""),
                    }
                else:
                    # SFG subcontract item (original behavior)
                    po_data = {
                        "fg_item": row.production_item,
                        "warehouse": row.fg_warehouse,
                        "production_plan_sub_assembly_item": row.name,
                        "bom": row.bom_no,
                        "production_plan": self.name,
                        "fg_item_qty": row.qty,
                    }

                    for field in [
                        "schedule_date",
                        "qty",
                        "description",
                        "production_plan_item",
                    ]:
                        po_data[field] = row.get(field)

                po.append("items", po_data)

            if not po.items:
                continue

            po.set_service_items_for_finished_goods()
            po.set_missing_values()
            po.flags.ignore_mandatory = True
            po.flags.ignore_validate = True
            po.insert()
            purchase_orders.append(po.name)
