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

	{"fieldname": "purchasing_doc_type","label": _("Purchasing Doc. Type"),"fieldtype": "Data","width": 140},

	{"fieldname": "document_date","label": _("Document Date"),"fieldtype": "Date","width": 110},
	{"fieldname": "po_number","label": _("Po Number"),"fieldtype": "Link","options": "Purchase Order","width": 150},
	{"fieldname": "po_item","label": _("Po Item"),"fieldtype": "Int","width": 80},

	{"fieldname": "supplier_code","label": _("Supplier Code"),"fieldtype": "Link","options": "Supplier","width": 140},
	{"fieldname": "supplier_description","label": _("Supplier Description"),"fieldtype": "Data","width": 200},

	{"fieldname": "material_code","label": _("Material Code"),"fieldtype": "Link","options": "Item","width": 140},
	{"fieldname": "short_text","label": _("Short Text"),"fieldtype": "Data","width": 200},

	{"fieldname": "supplier_gstin","label": _("Supplier Gstn No"),"fieldtype": "Data","width": 140},

	{"fieldname": "material_group","label": _("Material Group"),"fieldtype": "Link","options": "Item Group","width": 140},

	{"fieldname": "plant","label": _("Plant"),"fieldtype": "Link","options": "Company","width": 120},
	{"fieldname": "storage_location","label": _("Storage Location"),"fieldtype": "Link","options": "Warehouse","width": 140},

	{"fieldname": "po_delivery_date","label": _("Po Delivery Date"),"fieldtype": "Date","width": 110},

	{"fieldname": "order_qty","label": _("Order Quantity"),"fieldtype": "Float","width": 110},
	{"fieldname": "order_unit","label": _("Order Unit"),"fieldtype": "Link","options": "UOM","width": 90},

	{"fieldname": "net_price","label": _("Net Price"),"fieldtype": "Currency","width": 120},
	{"fieldname": "qty_net_price","label": _("Qnty Net Price"),"fieldtype": "Currency","width": 140},

	{"fieldname": "cgst","label": _("CGST"),"fieldtype": "Currency","width": 100},
	{"fieldname": "sgst","label": _("SGST"),"fieldtype": "Currency","width": 100},
	{"fieldname": "igst","label": _("IGST"),"fieldtype": "Currency","width": 100},

	{"fieldname": "net_price_tax","label": _("Net Price With Tax"),"fieldtype": "Currency","width": 150},

	{"fieldname": "material_document_number","label": _("Material Document Number"),"fieldtype": "Link","options": "Purchase Receipt","width": 160},
	{"fieldname": "goods_receipt_qty","label": _("Goods Receipt Quantity"),"fieldtype": "Float","width": 120},
	{"fieldname": "goods_receipt_unit","label": _("Goods Receipt Unit"),"fieldtype": "Link","options": "UOM","width": 110},

	{"fieldname": "posting_date","label": _("Posting Date"),"fieldtype": "Date","width": 110},

	{"fieldname": "supplier_document_no","label": _("Supplier Document No"),"fieldtype": "Data","width": 160},

	{"fieldname": "supplier_invoice_no","label": _("Supplier Invoice No"),"fieldtype": "Data","width": 160},
	{"fieldname": "supplier_document_date","label": _("Supplier Document Date"),"fieldtype": "Date","width": 110},

	{"fieldname": "invoice_basic_value","label": _("Invoice Basic Value"),"fieldtype": "Currency","width": 150},

	{"fieldname": "cgst_invoice","label": _("CGST Invoice"),"fieldtype": "Currency","width": 120},
	{"fieldname": "sgst_invoice","label": _("SGST Invoice"),"fieldtype": "Currency","width": 120},
	{"fieldname": "igst_invoice","label": _("IGST Invoice"),"fieldtype": "Currency","width": 120},

	{"fieldname": "total_invoice_value","label": _("Total Invoice Value"),"fieldtype": "Currency","width": 160},

	{"fieldname": "pending_qty","label": _("Pending Qty"),"fieldtype": "Float","width": 110},

	{"fieldname": "insurance_gl","label": _("Insurance GL"),"fieldtype": "Data","width": 150},
	{"fieldname": "insurance_amount","label": _("Insur Amount"),"fieldtype": "Currency","width": 130},

	{"fieldname": "freight_gl","label": _("Fright GL"),"fieldtype": "Data","width": 150},
	{"fieldname": "freight_amount","label": _("Fright Amount"),"fieldtype": "Currency","width": 130},

	{"fieldname": "total_accessible_value","label": _("Total Accessible Value"),"fieldtype": "Currency","width": 170},

	{"fieldname": "fcgst","label": _("FCGST Fri+Inv"),"fieldtype": "Currency","width": 120},
	{"fieldname": "fsgst","label": _("FSGST Fri+Inv"),"fieldtype": "Currency","width": 120},
	{"fieldname": "figst","label": _("FIGST Fri+Inv"),"fieldtype": "Currency","width": 120},

	]


def get_data(filters):

	conditions = get_conditions(filters)

	data = frappe.db.sql(f"""

	SELECT

	'PO' AS purchasing_doc_type,

	po.transaction_date AS document_date,
	po.name AS po_number,
	poi.idx AS po_item,

	po.supplier AS supplier_code,
	po.supplier_name AS supplier_description,

	poi.item_code AS material_code,
	poi.item_name AS short_text,

	po.supplier_gstin AS supplier_gstin,

	poi.item_group AS material_group,

	po.company AS plant,
	poi.warehouse AS storage_location,

	poi.schedule_date AS po_delivery_date,

	poi.qty AS order_qty,
	poi.uom AS order_unit,

	poi.net_rate AS net_price,
	poi.net_amount AS qty_net_price,

	IFNULL(poi.cgst_amount,0) AS cgst,
	IFNULL(poi.sgst_amount,0) AS sgst,
	IFNULL(poi.igst_amount,0) AS igst,

	(poi.net_amount
	+ IFNULL(poi.cgst_amount,0)
	+ IFNULL(poi.sgst_amount,0)
	+ IFNULL(poi.igst_amount,0)) AS net_price_tax,

	pr.name AS material_document_number,
	pri.qty AS goods_receipt_qty,
	pri.uom AS goods_receipt_unit,

	pr.posting_date AS posting_date,

	pr.supplier_delivery_note AS supplier_document_no,

	pi.bill_no AS supplier_invoice_no,
	pi.bill_date AS supplier_document_date,

	pii.net_amount AS invoice_basic_value,

	IFNULL(pii.cgst_amount,0) AS cgst_invoice,
	IFNULL(pii.sgst_amount,0) AS sgst_invoice,
	IFNULL(pii.igst_amount,0) AS igst_invoice,

	(pii.net_amount
	+ IFNULL(pii.cgst_amount,0)
	+ IFNULL(pii.sgst_amount,0)
	+ IFNULL(pii.igst_amount,0)) AS total_invoice_value,

	(poi.qty - IFNULL(poi.received_qty,0)) AS pending_qty,

	tax.insurance_gl,
	IFNULL(tax.insurance_amount,0) AS insurance_amount,

	tax.freight_gl,
	IFNULL(tax.freight_amount,0) AS freight_amount,

	(IFNULL(pii.net_amount,0)
	+ IFNULL(tax.freight_amount,0)
	+ IFNULL(tax.insurance_amount,0)) AS total_accessible_value,

	IFNULL(tax.cgst,0) AS fcgst,
	IFNULL(tax.sgst,0) AS fsgst,
	IFNULL(tax.igst,0) AS figst

	FROM `tabPurchase Order Item` poi

	JOIN `tabPurchase Order` po
	ON po.name = poi.parent
	AND po.docstatus = 1

	LEFT JOIN `tabPurchase Receipt Item` pri
	ON pri.purchase_order_item = poi.name

	LEFT JOIN `tabPurchase Receipt` pr
	ON pr.name = pri.parent
	AND pr.docstatus = 1

	LEFT JOIN `tabPurchase Invoice Item` pii
	ON pii.purchase_order = po.name
	AND pii.item_code = poi.item_code

	LEFT JOIN `tabPurchase Invoice` pi
	ON pi.name = pii.parent
	AND pi.docstatus = 1

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
	ON tax.parent = pi.name

	WHERE poi.docstatus = 1
	{conditions}

	ORDER BY po.transaction_date DESC, po.name, poi.idx

	""", filters, as_dict=True)

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

	return " ".join(conditions)