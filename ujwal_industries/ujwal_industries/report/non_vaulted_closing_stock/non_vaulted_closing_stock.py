import frappe
from frappe import _
from frappe.utils import nowdate


def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data



def get_columns(filters):
    return [
        {"label": _("Valution Area"), "fieldname": "valution_area", "fieldtype": "Data", "width": 150},
        {"label": _("Material"), "fieldname": "item", "fieldtype": "Link", "options": "Item", "width": 150},
        {"label": _("Material Description"), "fieldname": "item_description", "fieldtype": "Data", "width": 200},
        {"label": _("From Date"), "fieldname": "from_date", "fieldtype": "Date", "width": 100},
        {"label": _("To Date"), "fieldname": "to_date", "fieldtype": "Date", "width": 100},
        {"label": _("Opening Stock"), "fieldname": "opening_stock", "fieldtype": "Float", "width": 150},
        {"label": _("Total Receipt Qties"), "fieldname": "total_stock_qties", "fieldtype": "Float", "width": 170},
        {"label": _("Total Issue Quantities"), "fieldname": "total_issue_quantities", "fieldtype": "Float", "width": 200},
        {"label": _("Closing Stock"), "fieldname": "closing_stock", "fieldtype": "Float", "width": 150},
        {"label": _("Base Unit Of Measure"), "fieldname": "base_unit_measure", "options": "UOM" ,"fieldtype": "Link", "width": 170},
	]    
	

def get_data(filters):
	if not filters:
		filters = {}

	data = []
	conditions = ""

	if filters.get("item"):
		conditions += " AND ti.name = %(item)s"
  
	item_data = frappe.db.sql(f"""
		SELECT 
			ti.name ,
			ti.description ,
			ti.valuation_rate ,
			ti.stock_uom
		FROM `tabItem` ti
		WHERE 1=1
		{conditions}
	""", filters, as_dict=True)
 
	for i in item_data:
     
		data.append({
			'valution_area' : i.valuation_rate,
			'item' : i.name,
			'item_description' : i.description,
			'base_unit_measure' : i.stock_uom,
		})
	return data