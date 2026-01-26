import frappe
from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
from frappe.utils import flt
from erpnext.stock.doctype.stock_entry.stock_entry import FinishedGoodError

# Store original function check if operations completed
original_check = StockEntry.check_if_operations_completed

def check_if_operations_completed_wrapper(self):
		
        """Check if Time Sheets are completed against before manufacturing to capture operating costs."""
        prod_order = frappe.get_doc("Work Order", self.work_order) 
        allowance_percentage = flt(
			frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order")
		)
        for d in prod_order.get("operations"):
            total_completed_qty = flt(self.fg_completed_qty) + flt(prod_order.produced_qty)
            completed_qty = (
                d.completed_qty + d.process_loss_qty + (allowance_percentage / 100 * d.completed_qty)
            )
            if flt(total_completed_qty, self.precision("fg_completed_qty")) > flt(
                completed_qty, self.precision("fg_completed_qty")
            ):
                job_card = frappe.db.get_value("Job Card", {"operation_id": d.name}, "name")
                if not job_card:
                    frappe.throw(
                        ("Work Order {0}: Job Card not found for the operation {1}").format(
                            self.work_order, d.operation
                        )
                    )
# 3. Override in runtime
StockEntry.check_if_operations_completed = check_if_operations_completed_wrapper

# Store original function validate work order
original_validate_work_order = StockEntry.validate_work_order


def validate_work_order_wrapper(self):
    # 👉 Only override when Scrap checkbox is ticked
    if getattr(self, "custom_is_scrap_entry", 0):

        if self.purpose in (
			"Manufacture",
			"Material Transfer for Manufacture",
			"Material Consumption for Manufacture",
			"Disassemble",
		):
            if (
				self.purpose == "Manufacture" or self.purpose == "Material Consumption for Manufacture"
			) and self.work_order:
              self.check_if_operations_completed()
              self.check_duplicate_entry_for_work_order()
            elif self.purpose != "Material Transfer":
                self.work_order = None


# Monkey patch
StockEntry.validate_work_order = validate_work_order_wrapper

# Store original validate finished goods
_original_validate_finished_goods = StockEntry.validate_finished_goods


def validate_finished_goods_wrapper(self):

    # 👉 Scrap entry: skip FG validations
    if getattr(self, "custom_is_scrap_entry", 0):
        production_item, wo_qty, finished_items = None, 0, []
        if self.work_order:
            wo_details = frappe.db.get_value("Work Order", self.work_order, ["production_item", "qty"])
            if wo_details:
                production_item, wo_qty = wo_details
        for d in self.get("items"):
            if d.is_finished_item:
                if not self.work_order:
                    finished_items.append(d.item_code)
                    continue
                if d.item_code != production_item:
                    frappe.throw(
						("Finished Item {0} does not match with Work Order {1}").format(
							d.item_code, self.work_order
						)
					)
                elif flt(d.transfer_qty) > flt(self.fg_completed_qty):
                    frappe.throw(
						("Quantity in row {0} ({1}) must be same as manufactured quantity {2}").format(
							d.idx, d.transfer_qty, self.fg_completed_qty
						)
					)
                finished_items.append(d.item_code)
        if self.purpose == "Manufacture":
            if len(set(finished_items)) > 1:
                frappe.throw(
					msg=("Multiple items cannot be marked as finished item"),
					title=("Note"),
					exc=FinishedGoodError,
				)
            allowance_percentage = flt(
				frappe.db.get_single_value(
					"Manufacturing Settings", "overproduction_percentage_for_work_order"
				)
			)
            allowed_qty = wo_qty + ((allowance_percentage / 100) * wo_qty)
            if self.work_order and self.fg_completed_qty > allowed_qty:
                frappe.throw(
					("For quantity {0} should not be greater than allowed quantity {1}").format(
						flt(self.fg_completed_qty), allowed_qty
					)
				)


# Monkey patch
StockEntry.validate_finished_goods = validate_finished_goods_wrapper


import frappe
from frappe.utils import flt
from erpnext.manufacturing.doctype.work_order.work_order import WorkOrder
from erpnext.manufacturing.doctype.work_order.work_order import StockOverProductionError
from frappe import _


_original_update_work_order_qty = WorkOrder.update_work_order_qty


def get_item_tolerance_percentage(item_code):
    if not item_code:
        return 0
    return flt(
        frappe.db.get_value("Item", item_code, "custom_tolerance_") or 0
    )


def update_work_order_qty_wrapper(self):
    """Override: Update Manufactured Qty with Item Tolerance + Overproduction"""

    allowance_percentage = flt(
        frappe.db.get_single_value(
            "Manufacturing Settings",
            "overproduction_percentage_for_work_order",
        )
    )

    item_tolerance = get_item_tolerance_percentage(self.production_item)

    for purpose, fieldname in (
        ("Manufacture", "produced_qty"),
        ("Material Transfer for Manufacture", "material_transferred_for_manufacturing"),
    ):
        if (
            purpose == "Material Transfer for Manufacture"
            and self.operations
            and self.transfer_material_against == "Job Card"
        ):
            continue

        qty = self.get_transferred_or_manufactured_qty(purpose)

        allowed_qty = (
            self.qty
            + ((allowance_percentage / 100) * self.qty)
            + ((item_tolerance / 100) * self.qty)
        )

        if qty > allowed_qty:
            frappe.throw(
                _(
                    "{0} ({1}) cannot be greater than allowed quantity ({2}) "
                    "(WO Qty: {3}, Overproduction: {4}%, Item Tolerance: {5}%) "
                    "in Work Order {6}"
                ).format(
                    _(self.meta.get_label(fieldname)),
                    flt(qty),
                    flt(allowed_qty),
                    self.qty,
                    allowance_percentage,
                    item_tolerance,
                    self.name,
                ),
                StockOverProductionError,
            )

        self.db_set(fieldname, qty)
        self.set_process_loss_qty()

        from erpnext.selling.doctype.sales_order.sales_order import (
            update_produced_qty_in_so_item,
        )

        if self.sales_order and self.sales_order_item:
            update_produced_qty_in_so_item(
                self.sales_order, self.sales_order_item
            )

    if self.production_plan:
        self.set_produced_qty_for_sub_assembly_item()
        self.update_production_plan_status()


# Monkey patch
WorkOrder.update_work_order_qty = update_work_order_qty_wrapper
