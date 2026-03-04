
from frappe import _

def update_po_dashboard(data):
    return {
		"fieldname": "purchase_order",
		"non_standard_fieldnames": {
			"Journal Entry": "reference_name",
			"Payment Entry": "reference_name",
			"Payment Request": "reference_name",
			"Auto Repeat": "reference_document",
			"Gate Pass": "po_number",
		},
		"internal_links": {
			"Material Request": ["items", "material_request"],
			"Supplier Quotation": ["items", "supplier_quotation"],
			"Project": ["items", "project"],
			"Sales Order": ["items", "sales_order"],
			"BOM": ["items", "bom"],
			"Production Plan": ["items", "production_plan"],
			"Blanket Order": ["items", "blanket_order"],
		},
		"transactions": [
			{"label": _("Related"), "items": ["Purchase Receipt", "Purchase Invoice", "Sales Order"]},
			{"label": _("Payment"), "items": ["Payment Entry", "Journal Entry", "Payment Request"]},
			{
				"label": _("Reference"),
				"items": ["Supplier Quotation", "Project", "Auto Repeat", "Gate Pass"],
			},
			{
				"label": _("Manufacturing"),
				"items": ["Material Request", "BOM", "Production Plan", "Blanket Order"],
			},
			{
				"label": _("Sub-contracting"),
				"items": ["Subcontracting Order", "Subcontracting Receipt", "Stock Entry"],
			},
		],
	}
