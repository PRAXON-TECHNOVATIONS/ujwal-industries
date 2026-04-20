# Copyright (c) 2026, Ujwal Industries
# License: MIT

"""
BOM Overrides

Monkey-patches ERPNext BOM functions to use custom_batchsize instead of batch_size.
This ensures operation costing calculations use the custom batch size field.
"""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.model.naming import make_autoname


def update_bom_update_cost(self, update_parent=True, from_child_bom=False, update_hour_rate=True, save=True):
    """
    Monkey-patch for BOM.update_cost() to use custom_batchsize in operation cost calculations.

    Calculates operating costs and uses custom_batchsize for per-unit cost division.
    """
    if self.docstatus == 2:
        return

    if self.items:
        self.child_bom_cost = sum(
            flt(d.amount) for d in self.items if d.bom_no and d.bom_no != self.name
        )

    if self.operations:
        self.calculate_op_cost(update_hour_rate)
        self.calculate_op_cost_per_unit_with_custom_batchsize()

    if self.items:
        self.calculate_rm_cost(save=save)

    if self.scrap_items:
        self.total_scrap_cost = sum(flt(d.amount) for d in self.scrap_items)

    self.calculate_cost()

    if save:
        self.save()

    if update_parent and self.parent_bom:
        parent_bom = frappe.get_doc("BOM", self.parent_bom)
        parent_bom.update_cost(from_child_bom=True, update_hour_rate=update_hour_rate, save=save)


def calculate_op_cost_per_unit_with_custom_batchsize(self):
    """
    Calculate operation cost per unit using custom_batchsize.

    For each operation row:
    - cost_per_unit = operating_cost / custom_batchsize
    - base_cost_per_unit = base_operating_cost / custom_batchsize
    """
    for row in self.operations:
        batch_size = flt(row.get("custom_batchsize") or row.get("batch_size") or 1.0)

        if batch_size <= 0:
            batch_size = 1.0

        row.cost_per_unit = flt(row.operating_cost) / batch_size
        row.base_cost_per_unit = flt(row.base_operating_cost) / batch_size


def update_bom_validate_operations(self):
    """
    Monkey-patch for BOM.validate_operations() to validate custom_batchsize.

    Ensures custom_batchsize is set and defaults to 1 if missing or invalid.
    """
    if not self.operations:
        return

    for row in self.operations:
        if not row.get("custom_batchsize") or flt(row.custom_batchsize) <= 0:
            row.custom_batchsize = 1

        if "batch_size" in row.as_dict():
            row.batch_size = row.custom_batchsize


def apply_bom_overrides():
    """
    Apply monkey patches to BOM class methods.

    This function should be called from hooks.py during app initialization.
    """
    try:
        from erpnext.manufacturing.doctype.bom.bom import BOM

        BOM.update_cost = update_bom_update_cost
        BOM.calculate_op_cost_per_unit_with_custom_batchsize = calculate_op_cost_per_unit_with_custom_batchsize
        BOM.validate_operations = update_bom_validate_operations

        original_calculate_op_cost = BOM.calculate_op_cost

        def patched_calculate_op_cost(self, update_hour_rate=False):
            original_calculate_op_cost(self, update_hour_rate)
            self.calculate_op_cost_per_unit_with_custom_batchsize()

        BOM.calculate_op_cost = patched_calculate_op_cost

    except ImportError:
        frappe.log_error("Failed to import BOM for monkey patching", "BOM Override Error")


def validate_default_tool(doc, method):
    operation_default_map = {}

    for row in doc.custom_tool_details or []:
        if row.is_default:
            if row.operation in operation_default_map:
                frappe.throw(
                    _("For Operation <b>{0}</b>, only one Tool can be marked as Default.")
                    .format(row.operation)
                )
            operation_default_map[row.operation] = row.tool


def validate_bom(doc, method):
    validate_default_tool(doc, method)

    tool_operations = {
        row.operation
        for row in (doc.custom_tool_details or [])
        if row.operation and row.tool
    }

    for op in doc.operations or []:
        machines = []
        if op.custom_workstations_csv:
            machines = [machine.strip() for machine in op.custom_workstations_csv.split(",") if machine.strip()]

        op.custom_machine_count = len(machines)

        if op.operation in tool_operations:
            if flt(op.custom_fixed_lot_capacity):
                frappe.throw(
                    _("Lot Capacity cannot be defined for Operation <b>{0}</b> because a Tool is linked to it.")
                    .format(op.operation)
                )

            op.custom_fixed_lot_capacity = 0
            
    if doc.amended_from:     
        doc.route = None

def autoname(doc, method):    
    if not doc.item:
        return

    base = f"BOM-{doc.item}"
    if not frappe.db.exists("BOM", base):
        doc.name = base
        return

    if doc.items:
        for d in doc.items:
            name = f"{base}-{d.item_code}"

            if not frappe.db.exists("BOM", name):
                doc.name = name
                return

    count = frappe.db.count("BOM", {"name": ["like", f"{base}%"]})
    doc.name = f"{base}-{count+1}"
    
def before_save(doc, method):
    if doc.amended_from:
        if frappe.db.exists("BOM", doc.amended_from):
            frappe.delete_doc("BOM", doc.amended_from, force=1)
            doc.amended_from = None
            
        doc.name = None

def after_insert(doc, method):
    if not doc.route:
        doc.db_set("route", doc.name)




@frappe.whitelist()
def get_tools_under_category():
    data = ["Tool"]
    Asset_catagory = frappe.get_all("Asset Category", filters={'parent_asset_category': "Tool"})
    for i in Asset_catagory:
        data.append(i.name)
    
    return data    
    