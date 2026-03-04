import frappe
from frappe import _
from frappe.utils import nowdate
from bs4 import BeautifulSoup


def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data



def get_columns(filters):
    return [
        {"label": _("Vendor Name"), "fieldname": "vendor_name", "fieldtype": "Link", "options": "Supplier" ,"width": 280},
        {"label": _("Purchase Order"), "fieldname": "purchase_order", "fieldtype": "Link", "options": "Purchase Order", "width": 190},
        {"label": _("Challan INV"), "fieldname": "challan_inv", "fieldtype": "Data", "width": 200},
        {"label": _("Material"), "fieldname": "item", "fieldtype": "Link", "options": "Item","width": 100},
        {"label": _("Material Description"), "fieldname": "item_description", "fieldtype": "Data", "width": 200},
        {"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 120},
        {"label": _("Quantity Issued"), "fieldname": "quantity_issued", "fieldtype": "Float", "width": 150},
        {"label": _("GR Recieved Qty"), "fieldname": "gr_recieved_qty", "fieldtype": "Float", "width": 170},
        {"label": _("Ch. Open Quantity"), "fieldname": "ch_open_qty", "fieldtype": "Float", "width": 200},
        {"label": _("Mov"), "fieldname": "mov", "fieldtype": "Data", "width": 150},
        {"label": _("Unit"), "fieldname": "unit", "fieldtype": "Link", "options": "UOM", "width": 150},
        {"label": _("Ch. Recon Qty"), "fieldname": "ch_recon_qty" ,"fieldtype": "Float", "width": 170},
        {"label": _("Subcontracting"), "fieldname": "subcontracting", "fieldtype": "Data", "width": 150},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 150},
        {"label": _("Reference Doc"), "fieldname": "doc", "fieldtype": "Data", "width": 150},
	]    
	

def get_data(filters):
	if not filters:
		filters = {}
  
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
 
	conditions = ""
	
	if filters.get("vendor_name"):
		conditions += " AND po.supplier = %(vendor_name)s"
  
	if from_date:
		conditions += " AND po.transaction_date >= %(from_date)s"

	if to_date:
		conditions += " AND po.transaction_date <= %(to_date)s"
  
	item_data = frappe.db.sql(f"""
        SELECT 
            po.supplier,
            po.name as purchase_order,
            poi.item_code,
            poi.description,
            po.transaction_date,
            poi.qty as po_qty,
            pri.received_qty as pr_qty,
            po.status
        FROM `tabPurchase Order` po
        LEFT JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
        LEFT JOIN `tabPurchase Receipt Item` pri ON pri.purchase_order_item = poi.name
        WHERE 1=1
        {conditions}
        ORDER BY po.supplier
    """, filters, as_dict=True)
	
	data = []
	grouped_data = {}
 
	for row in item_data:
		grouped_data.setdefault(row.supplier, []).append({
			"purchase_order": row.purchase_order,
			"item_code": row.item_code,
			"description": row.description,
			"transaction_date": row.transaction_date,
			"po_qty": row.po_qty,
			"pr_qty": row.pr_qty,
			"status": row.status,
		})
  
	for supplier, po_list in grouped_data.items():
     
		data.append({
			"indent": 0,
			"vendor_name": supplier,
		})

		for po in po_list:
			soup = BeautifulSoup(po["description"], "html.parser")
			clean_text = soup.get_text()
   
			data.append({
				"indent": 1,
				"purchase_order": po["purchase_order"],
				"item": po["item_code"],
				"item_description": clean_text,
				"posting_date": po['transaction_date'],
				"quantity_issued": po['po_qty'],
				"gr_recieved_qty": po['pr_qty'],
				"status": po['status'],
			})

	return data 