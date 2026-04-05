import frappe
from frappe import _
from frappe.utils import nowdate
from itertools import zip_longest


def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    return [
        {"label": _("GRN Number"), "fieldname": "purchase_receipt", "fieldtype": "Link", "options": "Purchase Receipt", "width": 180},
        {"label": _("GRN Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
        {"label": _("Supplier Invoice No"), "fieldname": "supplier_invoice_no", "fieldtype": "Data", "width": 180},
        {"label": _("Supplier Document Date"), "fieldname": "supplier_document_date", "fieldtype": "Date", "width": 200},
        {"label": _("Supplier Name"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 200},
        {"label": _("PO No"), "fieldname": "po_no", "fieldtype": "Link", "options": "Purchase Order", "width": 200},
        {"label": _("PO Date"), "fieldname": "po_date", "fieldtype": "Date", "width": 130},
        
        {"label": _("Material Code"), "fieldname": "item_code", "fieldtype": "Link", "options": 'Item',"width": 170},
        {"label": _("GRN Quantity"), "fieldname": "qty", "fieldtype": "Int", "width": 130},
        {"label": _("Material Description"), "fieldname": "item_descriptio", "fieldtype": "Data", "width": 200},
        {"label": _("PO Delivery Date"), "fieldname": "schedule_date", "fieldtype": "Date", "width": 150},
        
        {"label": _("Purchase Invoice Value (Basic)"), "fieldname": "net_total", "fieldtype": "Data", "width": 250},
        
        {"label": _("FG Description"), "fieldname": "fg_item_name", "fieldtype": "Link", "options": 'Item',"width": 200},
        {"label": _("Qty Produce"), "fieldname": "fg_completed_qty", "fieldtype": "Int", "width": 110},
        {"label": _("Qty Sale"), "fieldname": "qty_sale", "fieldtype": "Int", "width": 100},
        
        {"label": _("Sale Invoice No"), "fieldname": "sales_invoice", "fieldtype": "Link", "options": 'Sales Invoice', "width": 180},
        {"label": _("Sale Invoice Date"), "fieldname": "sales_invoice_date", "fieldtype": "Date", "width": 140},
        {"label": _("Sales Invoice Value (Basic)"), "fieldname": "base_net_total", "fieldtype": "Data", "width": 250},
        
	]    
	

def get_data(filters):
	if not filters:
		filters = {}
	
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
 
	pr_conditions = ""
	
	if filters.get("purchase_receipt"):
		pr_conditions += " AND pr.name = %(purchase_receipt)s"
  
	if from_date:
		pr_conditions += " AND pr.posting_date >= %(from_date)s"

	if to_date:
		pr_conditions += " AND pr.posting_date <= %(to_date)s"
    
	data = []
 
	pr_data = frappe.db.sql(f"""
		SELECT 
			pr.name as purchase_receipt,
			pr.posting_date,
			pr.bill_no,
			pr.bill_date,
			pr.supplier,
			pi.total
		FROM `tabPurchase Receipt` pr
		LEFT JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
		LEFT JOIN `tabPurchase Invoice Item` pii ON pii.pr_detail = pri.name
		LEFT JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent				
		WHERE 1=1
		AND pr.docstatus = 1
		{pr_conditions}
		GROUP BY pr.name
	""", filters, as_dict=True)
	
	for row in pr_data:
     
		po_item = []
		pi_item_list = frappe.get_all("Purchase Receipt Item", filters={'parent': row['purchase_receipt'], 'docstatus':1}, fields=['*'])
		for i in pi_item_list:
			if i.purchase_order not in po_item:
				po_item.append(i.purchase_order)

		po_date = None
		if po_item[0]:
			po_date = frappe.get_value("Purchase Order", po_item[0], 'transaction_date')
   
		data.append({
			"indent": 0,
			'purchase_receipt' : row['purchase_receipt'],
			'posting_date' : row['posting_date'],
			'supplier_invoice_no' : row['bill_no'],
			'supplier_document_date' : row['bill_date'],
			'supplier' : row['supplier'],
			'po_no' : po_item[0] if len(po_item) > 0 else '',	
			'po_date' : po_date,	
			'net_total' : row['total'],	
		})
  
		pr_items = frappe.db.sql("""
				SELECT 
					pri.item_code,
					pri.qty,
					pri.description,
					pri.parent,
					poi.schedule_date
				FROM `tabPurchase Receipt Item` pri
				LEFT JOIN `tabPurchase Order Item` poi ON pri.purchase_order_item = poi.name
				WHERE pri.parent = %s
			""", row["purchase_receipt"], as_dict=True)
	
		for pr in pr_items:
			data.append({
				"indent": 1,
				'item_code' : pr['item_code'],
				'qty' : pr['qty'],
				'item_descriptio' : pr['description'],
				'schedule_date' : pr['schedule_date'],
			})

	# ////////////////////////////////////////////////////////////////////
	se_conditions = ""
	
	if from_date:
		se_conditions += " AND se.posting_date >= %(from_date)s"

	if to_date:
		se_conditions += " AND se.posting_date <= %(to_date)s"
  
	sales_data_1 = []
	sales_data = frappe.db.sql(f"""
		SELECT 
			se.name as stock_entry,
			se.posting_date,
			sed.item_code,
			sed.qty
		FROM `tabStock Entry` se
		LEFT JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		WHERE 1=1
		AND se.docstatus = 1
		AND se.stock_entry_type = 'Manufacture'
		AND sed.is_finished_item = 1
		{se_conditions}
	""", filters, as_dict=True)
	
	for sales in sales_data:
		sales_data_1.append({
			'fg_item_name': sales['item_code'],
			'fg_completed_qty': sales['qty'],
		})
  
		si_item = frappe.db.sql("""
				SELECT 
					sii.qty,
					si.name,
					si.posting_date,
					sii.base_net_amount
				FROM `tabSales Invoice Item` sii
				LEFT JOIN `tabSales Invoice` si ON si.name = sii.parent
				WHERE sii.item_code = %s
				AND si.posting_date = %s
			""", (sales['item_code'], sales['posting_date']), as_dict=True)
  
		for sitem in si_item:
			sales_data_1.append({
				'qty_sale': sitem['qty'],
				'sales_invoice': sitem['name'],
				'sales_invoice_date': sitem['posting_date'],
				'base_net_total': sitem['base_net_amount'],
			})
	
	output = []
  
	output = []

	data_len = len(data)
	sales_len = len(sales_data_1)

	for i in range(max(data_len, sales_len)):
		row = {}

		if i < data_len:
			row.update(data[i])

		if i < sales_len:
			row.update(sales_data_1[i])

		output.append(row)

	return output
   