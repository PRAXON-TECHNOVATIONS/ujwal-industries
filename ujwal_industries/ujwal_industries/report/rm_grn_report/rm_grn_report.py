# Copyright (c) 2026, Ujjwal Aggrawal and contributors
# For license information, please see license.txt

# import frappe


# def execute(filters=None):
# 	columns, data = [], []
# 	return columns, data

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [

		{"fieldname": "grn_date", "label": _("Grn Document Date"), "fieldtype": "Date", "width": 110},
		{"fieldname": "grn_no", "label": _("Material Document Number"), "fieldtype": "Link", "options": "Purchase Receipt", "width": 160},
		{"fieldname": "grn_qty", "label": _("Goods Receipt Quantity"), "fieldtype": "Float", "width": 120},

		{"fieldname": "item_code", "label": _("Material Code"), "fieldtype": "Link", "options": "Item", "width": 130},
		{"fieldname": "item_name", "label": _("Material Description"), "fieldtype": "Data", "width": 200},

		{"fieldname": "supplier_delivery_note", "label": _("Supplier Document No"), "fieldtype": "Data", "width": 150},

		{"fieldname": "invoice_nos", "label": _("Supplier Invoice No"), "fieldtype": "Data", "width": 180},
		{"fieldname": "invoice_date", "label": _("Supplier Document Date"), "fieldtype": "Date", "width": 110},

		{"fieldname": "invoice_basic_value", "label": _("Invoice Basic Value"), "fieldtype": "Currency", "width": 150},

		{"fieldname": "insurance_gl", "label": _("Insurance GL"), "fieldtype": "Data", "width": 150},
		{"fieldname": "insurance_amount", "label": _("Insurance/Other Charges"), "fieldtype": "Currency", "width": 150},

		{"fieldname": "freight_gl", "label": _("Freight GL"), "fieldtype": "Data", "width": 150},
		{"fieldname": "freight_amount", "label": _("Freight Amount"), "fieldtype": "Currency", "width": 140},

		{"fieldname": "cgst", "label": _("CGST Fre+Inv"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "sgst", "label": _("SGST Fre+Inv"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "igst", "label": _("IGST Fre+Inv"), "fieldtype": "Currency", "width": 120},

		{"fieldname": "po_no", "label": _("Po No"), "fieldtype": "Link", "options": "Purchase Order", "width": 150},
		{"fieldname": "po_date", "label": _("Po Date"), "fieldtype": "Date", "width": 110},

		{"fieldname": "po_qty", "label": _("Po Qty"), "fieldtype": "Float", "width": 110},
		{"fieldname": "total_grn", "label": _("Total Grn"), "fieldtype": "Float", "width": 110},

	]


def get_data(filters):

	conditions = get_conditions(filters)

	data = frappe.db.sql(
		f"""
		SELECT

			pr.posting_date                         AS grn_date,
			pr.name                                 AS grn_no,
			pri.qty                                 AS grn_qty,

			pri.item_code                           AS item_code,
			pri.item_name                           AS item_name,

			pr.supplier_delivery_note               AS supplier_delivery_note,

			inv.invoice_nos                         AS invoice_nos,
			inv.last_invoice_date                   AS invoice_date,
			IFNULL(inv.invoice_basic_value,0)       AS invoice_basic_value,

			IFNULL(tax.insurance_gl,'')             AS insurance_gl,
			IFNULL(tax.insurance_amount,0)          AS insurance_amount,

			IFNULL(tax.freight_gl,'')               AS freight_gl,
			IFNULL(tax.freight_amount,0)            AS freight_amount,

			IFNULL(tax.cgst,0)                      AS cgst,
			IFNULL(tax.sgst,0)                      AS sgst,
			IFNULL(tax.igst,0)                      AS igst,

			po.name                                 AS po_no,
			po.transaction_date                     AS po_date,

			IFNULL(poi.qty,0)                       AS po_qty,

			IFNULL(grn.total_grn,0)                 AS total_grn

		FROM `tabPurchase Receipt Item` pri

		JOIN `tabPurchase Receipt` pr
			ON pr.name = pri.parent
			AND pr.docstatus = 1

		LEFT JOIN `tabPurchase Order Item` poi
			ON poi.name = pri.purchase_order_item

		LEFT JOIN `tabPurchase Order` po
			ON po.name = poi.parent

		/* Total GRN per PO Item */
		LEFT JOIN (
			SELECT
				purchase_order_item,
				SUM(qty) AS total_grn
			FROM `tabPurchase Receipt Item`
			GROUP BY purchase_order_item
		) grn
		ON grn.purchase_order_item = pri.purchase_order_item


		/* Invoice Aggregation */
		LEFT JOIN (
			SELECT
				pii.purchase_receipt,
				pii.item_code,
				GROUP_CONCAT(DISTINCT pi.bill_no ORDER BY pi.bill_date SEPARATOR ', ') AS invoice_nos,
				MAX(pi.bill_date) AS last_invoice_date,
				SUM(pii.net_amount) AS invoice_basic_value,
				MAX(pi.name) AS invoice_id
			FROM `tabPurchase Invoice Item` pii
			JOIN `tabPurchase Invoice` pi
				ON pi.name = pii.parent
				AND pi.docstatus = 1
			GROUP BY pii.purchase_receipt, pii.item_code
		) inv
		ON inv.purchase_receipt = pr.name
		AND inv.item_code = pri.item_code


		/* Tax Aggregation */
		LEFT JOIN (
			SELECT
				parent,

				MAX(CASE WHEN account_head LIKE '%%Insurance%%' THEN account_head END) AS insurance_gl,
				SUM(CASE WHEN account_head LIKE '%%Insurance%%' THEN tax_amount END) AS insurance_amount,

				MAX(CASE WHEN account_head LIKE '%%Freight%%' THEN account_head END) AS freight_gl,
				SUM(CASE WHEN account_head LIKE '%%Freight%%' THEN tax_amount END) AS freight_amount,

				SUM(CASE WHEN account_head LIKE '%%CGST%%' THEN tax_amount END) AS cgst,
				SUM(CASE WHEN account_head LIKE '%%SGST%%' THEN tax_amount END) AS sgst,
				SUM(CASE WHEN account_head LIKE '%%IGST%%' THEN tax_amount END) AS igst

			FROM `tabPurchase Taxes and Charges`
			GROUP BY parent
		) tax
		ON tax.parent = inv.invoice_id


		WHERE pri.docstatus = 1
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

	if filters.get("supplier"):
		conditions.append("AND pr.supplier = %(supplier)s")

	if filters.get("item_code"):
		conditions.append("AND pri.item_code = %(item_code)s")

	return " ".join(conditions)