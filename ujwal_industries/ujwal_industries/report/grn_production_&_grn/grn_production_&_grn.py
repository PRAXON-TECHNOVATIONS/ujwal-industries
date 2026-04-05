import frappe
from frappe import _
from frappe.utils import nowdate

def execute(filters=None):
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    return [
        {"label": _("Material Request"), "fieldname": "material_request", "fieldtype": "Link", "options": "Material Request", "width": 200},
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 200},
        {"label": _("Material"), "fieldname": "material_item", "fieldtype": "Link", "options": "Item", "width": 200},
        {"label": _("Material Description"), "fieldname": "material_description", "fieldtype": "Data", "width": 200},
        {"label": _("Qty"), "fieldname": "qty", "fieldtype": "Int", "width": 200},
	]    
	

def get_data(filters):
	if not filters:
		filters = {}
  
	data = []
	conditions = ""

	if filters.get("material_request"):
		conditions += " AND mr.name = %(material_request)s"
  
	mr_data = frappe.db.sql(f"""
		SELECT 
			mr.name ,
			mr.transaction_date ,
			mri.item_code,
			mri.description,
			mri.qty
		FROM `tabMaterial Request` mr
		LEFT JOIN `tabMaterial Request Item` mri ON mri.parent = mr.name
		WHERE 1=1
		{conditions}
	""", filters, as_dict=True)
	
	for row in mr_data:
		data.append(
			{
				'material_request' : row.name,
				'date' : row.transaction_date,
				'material_item' : row.item_code,
				'material_description' : row.description,
				'qty' : row.qty,
			}
		)
	return data