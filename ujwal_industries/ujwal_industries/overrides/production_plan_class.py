# Copyright (c) 2026, Ujwal Industries
# License: MIT
# Override Production Plan class to handle FG subcontracting

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

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
        vendor_po_dict = {}
        default_warehouses = get_default_warehouse()

        # Modified: pass subcontracted_po and vendor_po_dict to FG method
        self.make_work_order_for_finished_goods(wo_list, subcontracted_po, vendor_po_dict, default_warehouses)
        self.make_work_order_for_subassembly_items(wo_list, subcontracted_po, vendor_po_dict, default_warehouses)
        
        self.make_subcontracted_purchase_order(subcontracted_po, po_list)
        self.make_vendor_purchase_orders(vendor_po_dict, po_list)
        
        self.show_list_created_message("Work Order", wo_list)
        self.show_list_created_message("Purchase Order", po_list)

    @frappe.whitelist()
    def make_material_request(self):
        """Create Material Requests grouped by Sales Order, request type, customer and target warehouse."""
        material_request_list = []
        material_request_map = {}

        for item in self.mr_items:
            item_doc = frappe.get_cached_doc("Item", item.item_code)
            material_request_type = item.material_request_type or item_doc.default_material_request_type
            target_warehouse = item.warehouse

            if not target_warehouse:
                frappe.throw(
                    _("Row #{0}: Target Warehouse is required before creating Material Request for item {1}.").format(
                        item.idx,
                        item.item_code,
                    )
                )

            key = "{}:{}:{}:{}".format(
                item.sales_order,
                material_request_type,
                item_doc.customer or "",
                target_warehouse,
            )
            schedule_date = item.schedule_date or add_days(nowdate(), cint(item_doc.lead_time_days))

            if key not in material_request_map:
                material_request_map[key] = frappe.new_doc("Material Request")
                material_request = material_request_map[key]
                material_request.update(
                    {
                        "transaction_date": nowdate(),
                        "status": "Draft",
                        "company": self.company,
                        "material_request_type": material_request_type,
                        "customer": item_doc.customer or "",
                        "set_warehouse": target_warehouse,
                    }
                )
                material_request_list.append(material_request)
            else:
                material_request = material_request_map[key]

            material_request.append(
                "items",
                {
                    "item_code": item.item_code,
                    "from_warehouse": item.from_warehouse if material_request_type == "Material Transfer" else None,
                    "qty": item.quantity,
                    "schedule_date": schedule_date,
                    "warehouse": target_warehouse,
                    "sales_order": item.sales_order,
                    "production_plan": self.name,
                    "material_request_plan_item": item.name,
                    "project": frappe.db.get_value("Sales Order", item.sales_order, "project") if item.sales_order else None,
                },
            )

        for material_request in material_request_list:
            material_request.flags.ignore_permissions = 1
            material_request.run_method("set_missing_values")
            material_request.save()
            if self.get("submit_material_request"):
                material_request.submit()

        frappe.flags.mute_messages = False

        if material_request_list:
            material_request_list = [
                frappe.utils.get_link_to_form("Material Request", material_request.name)
                for material_request in material_request_list
            ]
            frappe.msgprint(_("{0} created").format(frappe.utils.comma_and(material_request_list)))
        else:
            frappe.msgprint(_("No material request created"))

    def make_work_order_for_finished_goods(self, wo_list, subcontracted_po, vendor_po_dict, default_warehouses):
        """
        Override to handle FG subcontracting and FG vendor labor items.
        If FG has custom_manufacturing_type == "Subcontract", add to subcontracted_po instead.
        If FG is "In House - Vendor", add to vendor_po_dict AND create Work Order.
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

            if fg_row and fg_row.get("custom_manufacturing_type") == "In House - Vendor":
                supplier = fg_row.get("custom_supplier")
                if supplier:
                    vendor_po_dict.setdefault(supplier, []).append({
                        "is_fg": True,
                        "item_code": fg_row.item_code,
                        "bom_no": fg_row.bom_no,
                        "qty": flt(fg_row.planned_qty) - flt(fg_row.ordered_qty),
                        "schedule_date": fg_row.planned_start_date,
                        "production_plan_item": fg_row.name,
                    })

            # Regular In House or In House - Vendor FG item - create Work Order
            if self.sub_assembly_items:
                item["use_multi_level_bom"] = 0

            set_default_warehouses(item, default_warehouses)
            work_order = self.create_work_order(item)
            if work_order:
                wo_list.append(work_order)

    def make_work_order_for_subassembly_items(self, wo_list, subcontracted_po, vendor_po_dict, default_warehouses):
        for row in self.sub_assembly_items:
            if row.type_of_manufacturing == "Subcontract":
                subcontracted_po.setdefault(row.supplier, []).append(row)
                continue

            if getattr(row, "type_of_manufacturing", None) == "In House - Vendor":
                vendor_po_dict.setdefault(row.supplier, []).append({
                    "is_fg": False,
                    "item_code": row.production_item,
                    "bom_no": row.bom_no,
                    "qty": flt(row.qty) - flt(row.ordered_qty),
                    "schedule_date": row.schedule_date,
                    "production_plan_sub_assembly_item": row.name,
                })

            if row.type_of_manufacturing == "Material Request":
                continue

            work_order_data = {
                "wip_warehouse": default_warehouses.get("wip_warehouse"),
                "fg_warehouse": default_warehouses.get("fg_warehouse"),
                "company": self.get("company"),
            }

            if flt(row.qty) <= flt(row.ordered_qty):
                continue

            self.prepare_data_for_sub_assembly_items(row, work_order_data)

            if work_order_data.get("qty") <= 0:
                continue

            work_order = self.create_work_order(work_order_data)
            if work_order:
                wo_list.append(work_order)
                
    def prepare_data_for_sub_assembly_items(self, row, wo_data):
        for field in [
            "production_item",
            "item_name",
            "qty",
            "fg_warehouse",
            "description",
            "bom_no",
            "stock_uom",
            "bom_level",
            "schedule_date",
        ]:
            if row.get(field):
                wo_data[field] = row.get(field)

        wo_data["qty"] = flt(row.get("qty")) - flt(row.get("ordered_qty"))

        wo_data.update(
            {
                "use_multi_level_bom": 0,
                "production_plan": self.name,
                "production_plan_sub_assembly_item": row.name,
            }
        )

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

    def make_vendor_purchase_orders(self, vendor_po_dict, purchase_orders):
        """
        Create regular processing Purchase Orders for In House - Vendor items.
        Extracts Service Items from Subcontracting BOM.
        """
        if not vendor_po_dict:
            return

        for supplier, item_list in vendor_po_dict.items():
            po = frappe.new_doc("Purchase Order")
            po.company = self.company
            po.supplier = supplier
            po.is_subcontracted = 0

            # Get schedule date from first item
            first_item = item_list[0]
            po.schedule_date = getdate(first_item.get("schedule_date")) if first_item.get("schedule_date") else nowdate()

            # Consolidate items by service item
            service_item_map = {}

            for row in item_list:
                qty = row.get("qty", 0)
                if qty <= 0:
                    continue
                    
                item_code = row.get("item_code")
                bom_no = row.get("bom_no")
                
                # Fetch Subcontracting BOM
                sub_bom = frappe.db.get_value(
                    "Subcontracting BOM", 
                    {"finished_good": item_code, "finished_good_bom": bom_no, "is_active": 1},
                    ["name", "service_item", "conversion_factor"],
                    as_dict=True
                )
                
                if not sub_bom:
                    frappe.msgprint(_("No active Subcontracting BOM found for Item {0} and BOM {1}").format(item_code, bom_no))
                    continue
                
                service_item = sub_bom.service_item
                conversion_factor = flt(sub_bom.conversion_factor) or 1
                required_service_qty = flt(qty) * conversion_factor
                
                if service_item not in service_item_map:
                    service_item_map[service_item] = {
                        "item_code": service_item,
                        "qty": 0.0,
                        "schedule_date": row.get("schedule_date")
                    }
                    
                service_item_map[service_item]["qty"] += required_service_qty

            for srv_item, srv_data in service_item_map.items():
                po.append("items", {
                    "item_code": srv_item,
                    "qty": srv_data["qty"],
                    "schedule_date": srv_data["schedule_date"]
                })

            if po.items:
                po.set_missing_values()
                po.flags.ignore_mandatory = True
                po.flags.ignore_validate = True
                po.insert()
                purchase_orders.append(po.name)

    def create_work_order(self, item):
        from erpnext.manufacturing.doctype.work_order.work_order import OverProductionError

        if flt(item.get("qty")) <= 0:
            return

        wo = frappe.new_doc("Work Order")
        wo.update(item)
        wo.planned_start_date = item.get("planned_start_date") or item.get("schedule_date")

        if item.get("warehouse"):
            wo.fg_warehouse = item.get("warehouse")

        wo.set_work_order_operations()
        
        if 'production_plan_item' in item:
            row_data = frappe.get_doc("Production Plan Item", item.get('production_plan_item'))
        else:
            row_data = frappe.get_doc("Production Plan Sub Assembly Item", item.get('production_plan_sub_assembly_item'))

        if row_data.custom_workstation:
            workstation_list = [ws.strip() for ws in row_data.custom_workstation.split(',') if ws.strip()]

            if workstation_list:
                final_operation = []
                row_count = len(workstation_list)
                idx = 1

                for operation_row in wo.operations:
                    base_time = flt(operation_row.time_in_mins)
                    split_time = base_time if operation_row.fixed_time else base_time / row_count
                    op_dict = operation_row.as_dict()

                    for workstation in workstation_list:
                        temp = op_dict.copy()
                        temp['workstation'] = workstation
                        temp['time_in_mins'] = split_time
                        temp['idx'] = idx
                        idx += 1
                        final_operation.append(temp)

                wo.operations = []
                for rec in final_operation:
                    wo.append('operations', rec)

        wo.set_required_items()

        try:
            wo.flags.ignore_mandatory = True
            wo.flags.ignore_validate = True
            wo.insert()
            return wo.name
        except OverProductionError:
            pass