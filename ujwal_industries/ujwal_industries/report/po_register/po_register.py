import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        # --- PO Info ---
        {
            "fieldname": "po_date",
            "label": _("PO Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "fieldname": "po_no",
            "label": _("PO No"),
            "fieldtype": "Link",
            "options": "Purchase Order",
            "width": 160,
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
            "fieldname": "supplier_gstin",
            "label": _("Supplier GSTIN"),
            "fieldtype": "Data",
            "width": 140,
        },
        {
            "fieldname": "item_code",
            "label": _("Material"),
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
            "label": _("Material Group"),
            "fieldtype": "Link",
            "options": "Item Group",
            "width": 130,
        },
        {
            "fieldname": "warehouse",
            "label": _("Storage Location"),
            "fieldtype": "Link",
            "options": "Warehouse",
            "width": 150,
        },
        {
            "fieldname": "order_qty",
            "label": _("Order Quantity"),
            "fieldtype": "Float",
            "width": 110,
        },
        {
            "fieldname": "delivery_date",
            "label": _("Delivery Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "fieldname": "uom",
            "label": _("Order Unit"),
            "fieldtype": "Link",
            "options": "UOM",
            "width": 80,
        },
        {
            "fieldname": "net_rate",
            "label": _("Net Price"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "order_basic_value",
            "label": _("Order Basic Value"),
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "fieldname": "po_cgst",
            "label": _("CGST (PO)"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "po_sgst",
            "label": _("SGST (PO)"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "po_igst",
            "label": _("IGST (PO)"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "order_gross_value",
            "label": _("Order Gross Value"),
            "fieldtype": "Currency",
            "width": 140,
        },
        # --- GRN Info ---
        {
            "fieldname": "grn_qty",
            "label": _("GRN Qty"),
            "fieldtype": "Float",
            "width": 90,
        },
        {
            "fieldname": "grn_date",
            "label": _("GRN Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "fieldname": "grn_nos",
            "label": _("GRN No"),
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "fieldname": "supplier_delivery_note",
            "label": _("Supplier Doc No"),
            "fieldtype": "Data",
            "width": 140,
        },
        # --- Pending ---
        {
            "fieldname": "pending_qty",
            "label": _("Pending Qty"),
            "fieldtype": "Float",
            "width": 100,
        },
        # --- Invoice Info ---
        {
            "fieldname": "invoice_nos",
            "label": _("Invoice No"),
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "fieldname": "invoice_date",
            "label": _("Invoice Date"),
            "fieldtype": "Date",
            "width": 100,
        },
        {
            "fieldname": "invoice_basic_value",
            "label": _("Invoice Basic Value"),
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "fieldname": "inv_cgst",
            "label": _("CGST (Inv)"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "inv_sgst",
            "label": _("SGST (Inv)"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "inv_igst",
            "label": _("IGST (Inv)"),
            "fieldtype": "Currency",
            "width": 110,
        },
        {
            "fieldname": "invoice_gross_value",
            "label": _("Invoice Gross Value"),
            "fieldtype": "Currency",
            "width": 150,
        },
    ]


def get_data(filters):
    conditions = get_conditions(filters)

    data = frappe.db.sql(
        f"""
        SELECT
            po.transaction_date          AS po_date,
            po.name                      AS po_no,
            po.supplier                  AS supplier,
            po.supplier_name             AS supplier_name,
            po.supplier_gstin            AS supplier_gstin,
            poi.item_code                AS item_code,
            poi.item_name                AS item_name,
            poi.item_group               AS item_group,
            poi.warehouse                AS warehouse,
            poi.qty                      AS order_qty,
            poi.schedule_date            AS delivery_date,
            poi.uom                      AS uom,
            poi.net_rate                 AS net_rate,
            poi.net_amount               AS order_basic_value,
            IFNULL(poi.cgst_amount, 0)   AS po_cgst,
            IFNULL(poi.sgst_amount, 0)   AS po_sgst,
            IFNULL(poi.igst_amount, 0)   AS po_igst,
            (poi.net_amount
                + IFNULL(poi.cgst_amount, 0)
                + IFNULL(poi.sgst_amount, 0)
                + IFNULL(poi.igst_amount, 0))  AS order_gross_value,

            IFNULL(grn.total_grn_qty, 0)           AS grn_qty,
            grn.last_grn_date                       AS grn_date,
            grn.grn_nos                             AS grn_nos,
            grn.supplier_delivery_note              AS supplier_delivery_note,

            (poi.qty - IFNULL(poi.received_qty, 0)) AS pending_qty,

            inv.invoice_nos                         AS invoice_nos,
            inv.last_invoice_date                   AS invoice_date,
            IFNULL(inv.invoice_basic_value, 0)      AS invoice_basic_value,
            IFNULL(inv.inv_cgst, 0)                 AS inv_cgst,
            IFNULL(inv.inv_sgst, 0)                 AS inv_sgst,
            IFNULL(inv.inv_igst, 0)                 AS inv_igst,
            IFNULL(inv.invoice_gross_value, 0)      AS invoice_gross_value

        FROM `tabPurchase Order Item` poi
        JOIN `tabPurchase Order` po
            ON po.name = poi.parent
            AND po.docstatus = 1

        /* ── GRN sub-query: aggregate all submitted PRs per PO item ── */
        LEFT JOIN (
            SELECT
                pri.purchase_order_item,
                SUM(pri.qty)                                               AS total_grn_qty,
                MAX(pr.posting_date)                                       AS last_grn_date,
                GROUP_CONCAT(DISTINCT pr.name ORDER BY pr.posting_date SEPARATOR ', ')
                                                                           AS grn_nos,
                MAX(pr.supplier_delivery_note)                             AS supplier_delivery_note
            FROM `tabPurchase Receipt Item` pri
            JOIN `tabPurchase Receipt` pr
                ON pr.name = pri.parent
                AND pr.docstatus = 1
            GROUP BY pri.purchase_order_item
        ) grn ON grn.purchase_order_item = poi.name

        /* ── Invoice sub-query: aggregate all submitted PIs per PO + item ── */
        LEFT JOIN (
            SELECT
                pii.purchase_order,
                pii.item_code,
                GROUP_CONCAT(DISTINCT pi.bill_no ORDER BY pi.bill_date SEPARATOR ', ')
                                                                           AS invoice_nos,
                MAX(pi.bill_date)                                          AS last_invoice_date,
                SUM(pii.net_amount)                                        AS invoice_basic_value,
                SUM(IFNULL(pii.cgst_amount, 0))                           AS inv_cgst,
                SUM(IFNULL(pii.sgst_amount, 0))                           AS inv_sgst,
                SUM(IFNULL(pii.igst_amount, 0))                           AS inv_igst,
                SUM(pii.net_amount
                    + IFNULL(pii.cgst_amount, 0)
                    + IFNULL(pii.sgst_amount, 0)
                    + IFNULL(pii.igst_amount, 0))                         AS invoice_gross_value
            FROM `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi
                ON pi.name = pii.parent
                AND pi.docstatus = 1
            GROUP BY pii.purchase_order, pii.item_code
        ) inv ON inv.purchase_order = po.name AND inv.item_code = poi.item_code

        WHERE poi.docstatus = 1
        {conditions}
        ORDER BY po.transaction_date DESC, po.name, poi.idx
        """,
        filters,
        as_dict=True,
    )

    return data


def get_conditions(filters):
    conditions = []

    if filters.get("from_date"):
        conditions.append("AND po.transaction_date >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("AND po.transaction_date <= %(to_date)s")
    if filters.get("company"):
        conditions.append("AND po.company = %(company)s")
    if filters.get("supplier"):
        conditions.append("AND po.supplier = %(supplier)s")
    if filters.get("item_code"):
        conditions.append("AND poi.item_code = %(item_code)s")
    if filters.get("item_group"):
        conditions.append("AND poi.item_group = %(item_group)s")
    if filters.get("warehouse"):
        conditions.append("AND poi.warehouse = %(warehouse)s")
    if filters.get("status"):
        conditions.append("AND po.status = %(status)s")

    return " ".join(conditions)
