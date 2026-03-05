import frappe
from frappe import _
from frappe.utils import nowdate

def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    return [
        {"label": _("GATE ENTRY"), "fieldname": "gate_pass", "fieldtype": "Link", "options": "Gate Pass", "width": 200},
        {"label": _("PO NUMBER"), "fieldname": "po_number", "fieldtype": "Link", "options": "Purchase Order", "width": 200},
        {"label": _("VENDOR INVOICE"), "fieldname": "supplier_invoice_no", "fieldtype": "Link", "options": "Purchase Order", "width": 200},
        {"label": _("VEHICLE NO."), "fieldname": "vehicle_no", "fieldtype": "Data", "width": 120},
        {"label": _("VEHICLE IN TIME"), "fieldname": "vehicle_in_time", "fieldtype": "Time", "width": 150},
        {"label": _("SUPPLIER"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 200},
        {"label": _("GATE ENTRY DATE"), "fieldname": "posting_date", "fieldtype": "Date", "width": 170},
        {"label": _("PLANT"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 200},
        {"label": _("MATERIAL"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 200},
        {"label": _("GATE ENTRY QUANTITY"), "fieldname": "gate_qty", "fieldtype": "Int", "width": 200},
        {"label": _("PO QTY"), "fieldname": "po_qty", "fieldtype": "Int", "width": 100},
        {"label": _("PO DATE"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 110},
        {"label": _("GR DOC"), "fieldname": "purchase_receipt", "fieldtype": "Link", "options": "Purchase Receipt", "width": 170},
        {"label": _("GR TIME"), "fieldname": "posting_time", "fieldtype": "Time", "width": 100},
        {"label": _("GR DATE"), "fieldname": "gr_posting_date", "fieldtype": "Date", "width": 110},
        {"label": _("GR QTY"), "fieldname": "grn_qty", "fieldtype": "Int", "width": 100},
	]    
	

def get_data(filters):
	if not filters:
		filters = {}
	
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
 
	conditions = ""
	
	if filters.get("gate_pass"):
		conditions += " AND gp.name = %(gate_pass)s"
  
	if from_date:
		conditions += " AND gp.posting_date >= %(from_date)s"

	if to_date:
		conditions += " AND gp.posting_date <= %(to_date)s"
      
	gp_data = frappe.db.sql(f"""
        SELECT 
            gp.name as gate_pass,
            gp.posting_date,
            gp.po_number,
            gp.vehicle_no,
            gp.vehicle_in_time,
            gp.supplier,
            gp.plant,
            po.transaction_date,
            pr.name as purchase_receipt,
            pr.posting_time,
            pr.posting_date
        FROM `tabGate Pass` gp
        LEFT JOIN `tabPurchase Order` po ON po.name = gp.po_number
        LEFT JOIN `tabPurchase Receipt` pr ON pr.custom_gate_pass = gp.name
        WHERE 1=1
        AND gp.po_number IS NOT NULL
    	AND gp.po_number != ''
		AND gp.docstatus != 2
        {conditions}
    """, filters, as_dict=True)
 
	data = []
 
	for po in gp_data:
		pi_item = []
		pi_item_list = frappe.get_all("Purchase Invoice Item", filters={'purchase_order': po["po_number"]}, fields=['*'])
		for i in pi_item_list:
			if i.parent not in pi_item:
				pi_item.append(i.parent)
			
		data.append({
			"indent": 0,
			"gate_pass": po["gate_pass"],
			"po_number": po["po_number"],
			"posting_date": po["posting_date"],
			"vehicle_no": po["vehicle_no"],
			"vehicle_in_time": po["vehicle_in_time"],
			"supplier": po["supplier"],
			"warehouse": po["plant"],
			"transaction_date": po["transaction_date"],
			"purchase_receipt": po["purchase_receipt"],
			"posting_time": po["posting_time"],
			"gr_posting_date": po["posting_date"],
			"supplier_invoice_no": "', '".join(pi_item),
		})
  
		po_items = frappe.db.sql("""
			SELECT 
				poi.item_code,
				poi.qty,
				poi.parent,
				gpd.qty as gate_pass_qty,
				pri.received_qty
			FROM `tabPurchase Order Item` poi
			LEFT JOIN `tabGate Pass Detail` gpd ON gpd.po_item = poi.name
			LEFT JOIN `tabPurchase Receipt Item` pri ON pri.purchase_order_item = poi.name
			WHERE poi.parent = %s
		""", po["po_number"], as_dict=True)

		item_map = {}

		for item in po_items:
			code = item["item_code"]

			if code not in item_map:
				item_map[code] = {
					"item_code": code,
					"po_qty": item["qty"] or 0,
					"gate_qty": item["gate_pass_qty"] or 0,
					"grn_qty": item["received_qty"] or 0,
				}
		
		for val in item_map.values():
			data.append({
				"indent": 1,
				"item_code": val["item_code"],
				"po_qty": val["po_qty"],
				"gate_qty": val["gate_qty"],
				"grn_qty": val["grn_qty"],
			})

	return data 
