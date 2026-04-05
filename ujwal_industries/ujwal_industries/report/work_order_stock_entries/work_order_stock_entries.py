# Copyright (c) 2026, Ujwal Industries and contributors
# For license information, please see license.txt

"""
Work Order Stock Entries Report

This report shows Work Orders with their related Stock Entries in a tree structure:
- Parent rows: Work Order summary with totals
- Child rows: Individual Stock Entries (Material Transfer, Manufacture, Scrap)

Includes all stock movements related to the Work Order including scrap items.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    """Execute the Work Order Stock Entries Report."""
    if not filters:
        filters = frappe._dict()

    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    """Define report columns."""
    return [
        {
            "fieldname": "work_order",
            "label": _("Work Order"),
            "fieldtype": "Link",
            "options": "Work Order",
            "width": 180,
        },
        {
            "fieldname": "stock_entry",
            "label": _("Stock Entry"),
            "fieldtype": "Link",
            "options": "Stock Entry",
            "width": 150,
        },
        {
            "fieldname": "purpose",
            "label": _("Purpose"),
            "fieldtype": "Data",
            "width": 140,
        },
        {
            "fieldname": "status",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "fieldname": "production_item",
            "label": _("Production Item"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 150,
        },
        {
            "fieldname": "item_code",
            "label": _("Item Code"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 150,
        },
        {
            "fieldname": "item_name",
            "label": _("Item Name"),
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "fieldname": "is_scrap",
            "label": _("Is Scrap"),
            "fieldtype": "Check",
            "width": 80,
        },
        {
            "fieldname": "qty_to_produce",
            "label": _("Qty to Produce"),
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "fieldname": "produced_qty",
            "label": _("Produced Qty"),
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "fieldname": "required_qty",
            "label": _("Required Qty"),
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "fieldname": "transferred_qty",
            "label": _("Transferred Qty"),
            "fieldtype": "Float",
            "width": 120,
        },
        {
            "fieldname": "consumed_qty",
            "label": _("Consumed Qty"),
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "fieldname": "scrap_qty",
            "label": _("Scrap Qty"),
            "fieldtype": "Float",
            "width": 100,
        },
        {
            "fieldname": "uom",
            "label": _("UOM"),
            "fieldtype": "Link",
            "options": "UOM",
            "width": 70,
        },
        {
            "fieldname": "posting_date",
            "label": _("Posting Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "fieldname": "source_warehouse",
            "label": _("Source Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 140,
        },
        {
            "fieldname": "target_warehouse",
            "label": _("Target Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 140,
        },
    ]


def get_data(filters):
    """Get work order data with stock entries in tree structure."""
    conditions = get_conditions(filters)

    # Get Work Orders
    work_orders = frappe.db.sql(
        f"""
        SELECT
            wo.name as work_order,
            wo.status,
            wo.production_item,
            wo.qty as qty_to_produce,
            wo.produced_qty,
            wo.material_transferred_for_manufacturing as transferred_qty,
            wo.company,
            wo.planned_start_date
        FROM
            `tabWork Order` wo
        WHERE
            wo.docstatus = 1
            {conditions}
        ORDER BY
            wo.planned_start_date DESC, wo.name DESC
        """,
        filters,
        as_dict=True,
    )

    if not work_orders:
        return []

    # Get all stock entries for these work orders
    work_order_names = [wo.work_order for wo in work_orders]
    stock_entries = get_stock_entries(work_order_names)

    # Get work order items for required qty info
    wo_items = get_work_order_items(work_order_names)

    # Build tree structure data
    data = []
    for wo in work_orders:
        # Calculate totals for parent row
        wo_stock_entries = stock_entries.get(wo.work_order, [])
        wo_item_data = wo_items.get(wo.work_order, {})

        total_required = sum(item.get("required_qty", 0) for item in wo_item_data.values())
        total_consumed = sum(item.get("consumed_qty", 0) for item in wo_item_data.values())
        total_scrap = get_total_scrap_qty(wo.work_order, wo_stock_entries)

        # Parent row - Work Order summary
        parent_row = {
            "indent": 0,
            "work_order": wo.work_order,
            "stock_entry": None,
            "purpose": None,
            "status": wo.status,
            "production_item": wo.production_item,
            "item_code": None,
            "item_name": None,
            "is_scrap": 0,
            "qty_to_produce": wo.qty_to_produce,
            "produced_qty": wo.produced_qty,
            "required_qty": total_required,
            "transferred_qty": wo.transferred_qty,
            "consumed_qty": total_consumed,
            "scrap_qty": total_scrap,
            "uom": None,
            "posting_date": None,
            "source_warehouse": None,
            "target_warehouse": None,
        }
        data.append(parent_row)

        # Child rows - Stock Entries (indent=1) with their items (indent=2)
        for se in wo_stock_entries:
            se_items = se.get("items", [])
            # AVI
            # Special handling for Material Transfer
            mt_item_codes = []
            mt_item_names = []

            if se.purpose == "Material Transfer for Manufacture":
                mt_item_codes = [i.item_code for i in se_items]
                mt_item_names = [i.item_name for i in se_items]

            # AVI
            # Calculate totals for this Stock Entry
            se_total_qty = sum(flt(item.qty) for item in se_items)
            se_scrap_qty = sum(flt(item.qty) for item in se_items if item.is_scrap_item)
            se_consumed_qty = sum(
                flt(item.qty)
                for item in se_items
                if se.purpose == "Manufacture" and not item.is_scrap_item and not item.is_finished_item
            )
            se_transferred_qty = sum(
                flt(item.qty) for item in se_items if se.purpose == "Material Transfer for Manufacture"
            )

            # Stock Entry header row (indent=1)
            se_header_row = {
                "indent": 1,
                "work_order": wo.work_order,
                "stock_entry": se.stock_entry,
                "purpose": se.purpose,
                "status": None,
                "production_item": None,
                # AVI
                # "item_code": None,
                # "item_name": None,
                "item_code": (
                    join_unique(mt_item_codes)
                    if se.purpose == "Material Transfer for Manufacture"
                    else None
                ),
                "item_name": (
                    join_unique(mt_item_names)
                    if se.purpose == "Material Transfer for Manufacture"
                    else None
                ),
                # AVI
                "is_scrap": 1 if se_scrap_qty > 0 else 0,  # Mark if SE contains scrap
                "qty_to_produce": None,
                "produced_qty": None,
                "required_qty": None,
                "transferred_qty": se_transferred_qty if se_transferred_qty > 0 else None,
                "consumed_qty": se_consumed_qty if se_consumed_qty > 0 else None,
                "scrap_qty": se_scrap_qty if se_scrap_qty > 0 else None,
                "uom": None,
                "posting_date": se.posting_date,
                "source_warehouse": None,
                "target_warehouse": None,
            }
            data.append(se_header_row)

# AVI
            # Stock Entry items (indent=2)
            # if se_items:
            #     for item in se_items:
            #         item_row = {
            #             "indent": 2,
            #             "work_order": wo.work_order,
            #             "stock_entry": se.stock_entry,
            #             "purpose": None,  # Already shown in SE header
            #             "status": None,
            #             "production_item": None,
            #             "item_code": item.item_code,
            #             "item_name": item.item_name,
            #             "is_scrap": item.is_scrap_item,
            #             "qty_to_produce": None,
            #             # "produced_qty": None,
            #             "produced_qty": (
            #                         flt(item.qty)
            #                         if se.purpose == "Manufacture" and item.is_finished_item
            #                         else None
            #                     ),
            #             "required_qty": None,
            #             "transferred_qty": flt(item.qty) if se.purpose == "Material Transfer for Manufacture" else None,
            #             "consumed_qty": (
            #                 flt(item.qty)
            #                 if se.purpose == "Manufacture" and not item.is_scrap_item and not item.is_finished_item
            #                 else None
            #             ),
            #             "scrap_qty": flt(item.qty) if item.is_scrap_item else None,
            #             "uom": item.uom,
            #             "posting_date": None,  # Already shown in SE header
            #             "source_warehouse": item.s_warehouse,
            #             "target_warehouse": item.t_warehouse,
            #         }
            #         data.append(item_row)
            # Show item rows ONLY for non Material Transfer entries
            if se_items and se.purpose != "Material Transfer for Manufacture":
                for item in se_items:
                    item_row = {
                        "indent": 2,
                        "work_order": wo.work_order,
                        "stock_entry": se.stock_entry,
                        "purpose": None,
                        "status": None,
                        "production_item": None,
                        "item_code": item.item_code,
                        "item_name": item.item_name,
                        "is_scrap": item.is_scrap_item,
                        "qty_to_produce": None,
                        "produced_qty": (
                            flt(item.qty)
                            if se.purpose == "Manufacture" and item.is_finished_item
                            else None
                        ),
                        "required_qty": None,
                        "transferred_qty": flt(item.qty)
                        if se.purpose == "Material Transfer for Manufacture"
                        else None,
                        "consumed_qty": (
                            flt(item.qty)
                            if se.purpose == "Manufacture"
                            and not item.is_scrap_item
                            and not item.is_finished_item
                            else None
                        ),
                        "scrap_qty": flt(item.qty) if item.is_scrap_item else None,
                        "uom": item.uom,
                        "posting_date": None,
                        "source_warehouse": item.s_warehouse,
                        "target_warehouse": item.t_warehouse,
                    }
                    data.append(item_row)

# AVI

    return data


def get_conditions(filters):
    """Build SQL WHERE conditions from filters."""
    conditions = []

    if filters.get("work_order"):
        conditions.append("wo.name = %(work_order)s")

    if filters.get("production_item"):
        conditions.append("wo.production_item = %(production_item)s")

    if filters.get("company"):
        conditions.append("wo.company = %(company)s")

    if filters.get("status"):
        conditions.append("wo.status = %(status)s")

    if filters.get("from_date"):
        conditions.append("wo.creation >= %(from_date)s")

    if filters.get("to_date"):
        conditions.append("wo.creation <= %(to_date)s")

    return " AND " + " AND ".join(conditions) if conditions else ""


def get_stock_entries(work_order_names):
    """Get all stock entries for the given work orders, grouped by work order."""
    if not work_order_names:
        return {}

    # Get stock entries
    stock_entries = frappe.db.sql(
        """
        SELECT
            se.name as stock_entry,
            se.work_order,
            se.stock_entry_type as purpose,
            se.posting_date,
            se.docstatus
        FROM
            `tabStock Entry` se
        WHERE
            se.work_order IN %(work_orders)s
            AND se.docstatus = 1
        ORDER BY
            se.posting_date, se.name
        """,
        {"work_orders": work_order_names},
        as_dict=True,
    )

    if not stock_entries:
        return {}

    # Get stock entry items
    se_names = [se.stock_entry for se in stock_entries]
    items = frappe.db.sql(
        """
        SELECT
            sed.parent as stock_entry,
            sed.item_code,
            sed.item_name,
            sed.qty,
            sed.uom,
            sed.s_warehouse,
            sed.t_warehouse,
            sed.is_scrap_item,
            sed.is_finished_item
        FROM
            `tabStock Entry Detail` sed
        WHERE
            sed.parent IN %(stock_entries)s
        ORDER BY
            sed.idx
        """,
        {"stock_entries": se_names},
        as_dict=True,
    )

    # Group items by stock entry
    items_by_se = {}
    for item in items:
        items_by_se.setdefault(item.stock_entry, []).append(item)

    # Attach items to stock entries and group by work order
    entries_by_wo = {}
    for se in stock_entries:
        se["items"] = items_by_se.get(se.stock_entry, [])
        entries_by_wo.setdefault(se.work_order, []).append(se)

    return entries_by_wo


def get_work_order_items(work_order_names):
    """Get work order items for required/consumed qty info."""
    if not work_order_names:
        return {}

    items = frappe.db.sql(
        """
        SELECT
            woi.parent as work_order,
            woi.item_code,
            woi.item_name,
            woi.required_qty,
            woi.transferred_qty,
            woi.consumed_qty
        FROM
            `tabWork Order Item` woi
        WHERE
            woi.parent IN %(work_orders)s
        """,
        {"work_orders": work_order_names},
        as_dict=True,
    )

    # Group by work order and item
    items_by_wo = {}
    for item in items:
        wo = item.work_order
        if wo not in items_by_wo:
            items_by_wo[wo] = {}
        items_by_wo[wo][item.item_code] = item

    return items_by_wo


def get_total_scrap_qty(work_order, stock_entries):
    """Calculate total scrap qty from stock entries."""
    total_scrap = 0
    for se in stock_entries:
        for item in se.get("items", []):
            if item.is_scrap_item:
                total_scrap += flt(item.qty)
    return total_scrap


# AVI
def join_unique(values):
    """Join unique non-empty values with comma"""
    return ", ".join(sorted(set(v for v in values if v)))