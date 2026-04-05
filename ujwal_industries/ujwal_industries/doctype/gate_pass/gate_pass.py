# Copyright (c) 2026, Ujjwal Aggrawal and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import json
from frappe.utils import cint, cstr, flt, get_link_to_form
from frappe.model.mapper import get_mapped_doc
from erpnext.buying.doctype.purchase_order.purchase_order import set_missing_values

class GatePass(Document):
    pass
    
	# def validate(self):
	# 	self.validate_delivery_note_qty()
	# 	self.validate_po_qty()

	# def validate_delivery_note_qty(self):

	# 	if not self.delivery_note:
	# 		return

	# 	dn_items = frappe.get_all("Delivery Note Item", filters={ "parent": self.delivery_note},fields=["item_code", "qty"])

	# 	if not dn_items:
	# 		frappe.throw("No items found in selected Delivery Note")

	# 	dn_qty_map = {}
	# 	for d in dn_items:
	# 		dn_qty_map[d.item_code] = d.qty

	# 	gp_item_totals = {}

	# 	for row in self.gate_pass_detail:
	# 		if row.item not in dn_qty_map:
	# 			frappe.throw(
	# 				f"Item {row.item} not found in Delivery Note {self.delivery_note}"
	# 			)

	# 		gp_item_totals[row.item] = gp_item_totals.get(row.item, 0) + row.qty

	# 	for item_code, total_qty in gp_item_totals.items():
	# 		dn_qty = dn_qty_map.get(item_code)
	# 		if total_qty > dn_qty:
	# 			frappe.throw(
	# 				f"Total Qty for Item {item_code} "
	# 				f"({total_qty}) cannot exceed Delivery Note Qty ({dn_qty})"
	# 			)

	# def validate_po_qty(self):

	# 	if not self.po_number:
	# 		return

	# 	po_items = frappe.get_all("Purchase Order Item", filters={ "parent": self.po_number},fields=["item_code", "qty"])

	# 	if not po_items:
	# 		frappe.throw("No items found in selected Purchase Order")

	# 	po_qty_map = {}
	# 	for d in po_items:
	# 		po_qty_map[d.item_code] = d.qty

	# 	gp_item_totals = {}

	# 	for row in self.gate_pass_detail:
	# 		if row.item not in po_qty_map:
	# 			frappe.throw(
	# 				f"Item {row.item} not found in Purchase Order {self.po_number}"
	# 			)

	# 		gp_item_totals[row.item] = gp_item_totals.get(row.item, 0) + row.qty

	# 	for item_code, total_qty in gp_item_totals.items():
	# 		po_qty = po_qty_map.get(item_code)
	# 		if total_qty > po_qty:
	# 			frappe.throw(
	# 				f"Total Qty for Item {item_code} "
	# 				f"({total_qty}) cannot exceed Purchase Order Qty ({po_qty})"
	# 			)



@frappe.whitelist()
def get_delivery_note_items(delivery_note):
    
    if not delivery_note:
        return []
    
    dn_doc = frappe.get_doc("Delivery Note", delivery_note)
    
    items = []

    for row in dn_doc.items:
        items.append({
            "item": row.item_code,
            "qty": row.qty,
            "uom": row.uom,
            "description": row.description
        })

    return items


@frappe.whitelist()
def get_po_items(po_number):
	
	if not po_number:
		return []
	
	po_doc = frappe.get_doc("Purchase Order", po_number)
	
	items = []

	for row in po_doc.items:
		items.append({
			"item": row.item_code,
			"qty": row.qty,
			"uom": row.uom,
			"description": row.description,
			"po_item":row.name
		})
	return items




@frappe.whitelist()
def custom_make_purchase_receipt(source_name, gate_pass, target_doc=None, args=None):
	if args is None:
		args = {}
	if isinstance(args, str):
		args = json.loads(args)

	has_unit_price_items = frappe.db.get_value("Purchase Order", source_name, "has_unit_price_items")

	def is_unit_price_row(source):
		return has_unit_price_items and source.qty == 0

	def update_item(obj, target, source_parent):
		target.qty = flt(obj.qty) if is_unit_price_row(obj) else flt(obj.qty) - flt(obj.received_qty)
		target.stock_qty = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.conversion_factor)
		target.amount = (flt(obj.qty) - flt(obj.received_qty)) * flt(obj.rate)
		target.base_amount = (
			(flt(obj.qty) - flt(obj.received_qty)) * flt(obj.rate) * flt(source_parent.conversion_rate)
		)

	def select_item(d):
		filtered_items = args.get("filtered_children", [])
		child_filter = d.name in filtered_items if filtered_items else True
		return child_filter

	doc = get_mapped_doc(
		"Purchase Order",
		source_name,
		{
			"Purchase Order": {
				"doctype": "Purchase Receipt",
				"field_map": {"supplier_warehouse": "supplier_warehouse"},
				"validation": {
					"docstatus": ["=", 1],
				},
			},
			"Purchase Order Item": {
				"doctype": "Purchase Receipt Item",
				"field_map": {
					"name": "purchase_order_item",
					"parent": "purchase_order",
					"bom": "bom",
					"material_request": "material_request",
					"material_request_item": "material_request_item",
					"sales_order": "sales_order",
					"sales_order_item": "sales_order_item",
					"wip_composite_asset": "wip_composite_asset",
				},
				"postprocess": update_item,
				"condition": lambda doc: (
					True if is_unit_price_row(doc) else abs(doc.received_qty) < abs(doc.qty)
				)
				and doc.delivered_by_supplier != 1
				and select_item(doc),
			},
			"Purchase Taxes and Charges": {"doctype": "Purchase Taxes and Charges", "reset_value": True},
		},
		target_doc,
		set_missing_values,
	)
	doc.custom_gate_pass = gate_pass
	gp_doc = frappe.get_doc("Gate Pass",gate_pass)
	doc.bill_no = gp_doc.supplier_invoice
	for pr_item in doc.items:
		for gp_item in gp_doc.gate_pass_detail:
			if pr_item.item_code == gp_item.item:
				pr_item.received_qty = gp_item.qty
				pr_item.qty = gp_item.qty
	doc.save()
	return doc.name
