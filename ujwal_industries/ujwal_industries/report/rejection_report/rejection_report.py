import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        # --- Material Request ---
        {
            "fieldname": "mr_no",
            "label": _("Material Request"),
            "fieldtype": "Link",
            "options": "Material Request",
            "width": 170,
        },
        {
            "fieldname": "mr_date",
            "label": _("MR Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        # --- Purchase Order ---
        {
            "fieldname": "po_no",
            "label": _("Purchase Order"),
            "fieldtype": "Link",
            "options": "Purchase Order",
            "width": 170,
        },
        {
            "fieldname": "po_date",
            "label": _("PO Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "fieldname": "supplier",
            "label": _("Supplier Code"),
            "fieldtype": "Link",
            "options": "Supplier",
            "width": 120,
        },
        {
            "fieldname": "supplier_name",
            "label": _("Supplier Name"),
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "fieldname": "item_code",
            "label": _("Material Code"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 120,
        },
        {
            "fieldname": "item_name",
            "label": _("Short Text"),
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "fieldname": "item_group",
            "label": _("Item Group"),
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 130,
        },
        {
            "fieldname": "order_qty",
            "label": _("Order Quantity"),
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "fieldname": "net_rate",
            "label": _("Net Price"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "delivery_date",
            "label": _("Delivery Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        # --- Purchase Receipt (GRN) ---
        {
            "fieldname": "grn_no",
            "label": _("GRN No"),
            "fieldtype": "Link",
            "options": "Purchase Receipt",
            "width": 170,
        },
        {
            "fieldname": "posting_date",
            "label": _("GRN Posting Date"),
            "fieldtype": "Date",
            "width": 120,
        },
        {
            "fieldname": "supplier_delivery_note",
            "label": _("Challan / Bill No"),
            "fieldtype": "Data",
            "width": 140,
        },
        {
            "fieldname": "accepted_qty",
            "label": _("Accepted Qty"),
            "fieldtype": "Float",
            "width": 110,
        },
        # --- Rejection ---
        {
            "fieldname": "rejected_qty",
            "label": _("Rejection Qty Returned"),
            "fieldtype": "Float",
            "width": 150,
        },
        {
            "fieldname": "uom",
            "label": _("UOM"),
            "fieldtype": "Link",
            "options": "UOM",
            "width": 80,
        },
        {
            "fieldname": "rejected_warehouse",
            "label": _("Rejected Warehouse"),
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 160,
        },
    ]


def get_data(filters):
    conditions = get_conditions(filters)

    data = frappe.db.sql(
        f"""
        SELECT
            /* Material Request */
            poi.material_request          AS mr_no,
            mr.transaction_date           AS mr_date,

            /* Purchase Order */
            po.name                       AS po_no,
            po.transaction_date           AS po_date,
            po.supplier                   AS supplier,
            po.supplier_name              AS supplier_name,

            /* Item */
            pri.item_code                 AS item_code,
            pri.item_name                 AS item_name,
            poi.item_group                AS item_group,
            poi.qty                       AS order_qty,
            poi.net_rate                  AS net_rate,
            poi.schedule_date             AS delivery_date,

            /* GRN */
            pr.name                       AS grn_no,
            pr.posting_date               AS posting_date,
            pr.supplier_delivery_note     AS supplier_delivery_note,
            pri.qty                       AS accepted_qty,

            /* Rejection */
            pri.rejected_qty              AS rejected_qty,
            pri.uom                       AS uom,
            pri.rejected_warehouse        AS rejected_warehouse

        FROM `tabPurchase Receipt Item` pri

        JOIN `tabPurchase Receipt` pr
            ON pr.name = pri.parent
            AND pr.docstatus = 1

        JOIN `tabPurchase Order Item` poi
            ON poi.name = pri.purchase_order_item

        JOIN `tabPurchase Order` po
            ON po.name = poi.parent
            AND po.docstatus = 1

        LEFT JOIN `tabMaterial Request` mr
            ON mr.name = poi.material_request
            AND mr.docstatus = 1

        WHERE pri.rejected_qty > 0
        {conditions}
        ORDER BY pr.posting_date DESC, pr.name, pri.idx
        """,
        filters,
        as_dict=True,
    )

    return data


def get_conditions(filters):
    conditions = []

    if filters.get("from_date"):
        conditions.append("AND pr.posting_date >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("AND pr.posting_date <= %(to_date)s")
    if filters.get("company"):
        conditions.append("AND pr.company = %(company)s")
    if filters.get("supplier"):
        conditions.append("AND po.supplier = %(supplier)s")
    if filters.get("item_code"):
        conditions.append("AND pri.item_code = %(item_code)s")
    if filters.get("item_group"):
        conditions.append("AND poi.item_group = %(item_group)s")
    if filters.get("warehouse"):
        conditions.append("AND pri.rejected_warehouse = %(warehouse)s")
    if filters.get("purchase_order"):
        conditions.append("AND po.name = %(purchase_order)s")
    if filters.get("material_request"):
        conditions.append("AND poi.material_request = %(material_request)s")

    return " ".join(conditions)
