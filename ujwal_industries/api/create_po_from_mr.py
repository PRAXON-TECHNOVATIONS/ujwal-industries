import frappe
from frappe.model.mapper import get_mapped_doc

@frappe.whitelist()
def make_po_from_mr(material_request):
    def update_item_fields(source, target, source_parent):
        target.material_request = source_parent.name
        target.material_request_item = source.name

    po = get_mapped_doc(
        "Material Request",
        material_request,
        {
            "Material Request": {
                "doctype": "Purchase Order"
            },
            "Material Request Item": {
                "doctype": "Purchase Order Item",
                "postprocess": update_item_fields
            }
        }
    )
    return po