// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on('Production Plan', {
	refresh: function(frm) {
		// Auto-populate suppliers when form loads
		if (frm.doc.sub_assembly_items && frm.doc.sub_assembly_items.length > 0) {
			populate_subcontracting_suppliers(frm);
		}
	},

	// Hook into "Get Sub Assembly Items" button
	get_sub_assembly_items: function(frm) {
		// Wait for items to be added, then populate suppliers
		setTimeout(() => {
			populate_subcontracting_suppliers(frm);
		}, 500);
	}
});

// Child table event - when row is added or modified
frappe.ui.form.on('Production Plan Sub Assembly Item', {
	sub_assembly_items_add: function(frm, cdt, cdn) {
		// When new row is added
		populate_supplier_for_row(frm, cdt, cdn);
	},

	production_item: function(frm, cdt, cdn) {
		// When production item changes
		populate_supplier_for_row(frm, cdt, cdn);
	},

	type_of_manufacturing: function(frm, cdt, cdn) {
		// When type changes
		const row = locals[cdt][cdn];
		if (row.type_of_manufacturing === 'Subcontract' && !row.supplier) {
			populate_supplier_for_row(frm, cdt, cdn);
		} else if (row.type_of_manufacturing !== 'Subcontract') {
			// Clear supplier if not subcontract
			frappe.model.set_value(cdt, cdn, 'supplier', '');
		}
	}
});

/**
 * Populate suppliers for all subcontract items in the table
 */
function populate_subcontracting_suppliers(frm) {
	if (!frm.doc.sub_assembly_items || frm.doc.sub_assembly_items.length === 0) {
		return;
	}

	// Collect items that need supplier lookup
	const items_to_fetch = [];
	frm.doc.sub_assembly_items.forEach(row => {
		if (row.type_of_manufacturing === 'Subcontract' &&
		    !row.supplier &&
		    row.production_item) {
			items_to_fetch.push(row.production_item);
		}
	});

	if (items_to_fetch.length === 0) {
		return;
	}

	// Batch fetch default suppliers from server
	frappe.call({
		method: 'ujwal_industries.api.subcontracting_suppliers.get_default_subcontracting_suppliers',
		args: {
			items: items_to_fetch,
			company: frm.doc.company
		},
		callback: function(r) {
			if (r.message) {
				const supplier_map = r.message;
				console.log(supplier_map)

				// Populate supplier field for each row
				frm.doc.sub_assembly_items.forEach(row => {
					if (row.type_of_manufacturing === 'Subcontract' &&
					    !row.supplier &&
					    row.production_item in supplier_map) {
						frappe.model.set_value(
							row.doctype,
							row.name,
							'supplier',
							supplier_map[row.production_item].supplier
						);
					}
				});

				frm.refresh_field('sub_assembly_items');
				frappe.show_alert({
					message: __('Suppliers auto-populated for subcontract items'),
					indicator: 'green'
				}, 3);
			}
		}
	});
}

/**
 * Populate supplier for a single row
 */
function populate_supplier_for_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];

	// Only for subcontract items without supplier
	if (row.type_of_manufacturing !== 'Subcontract' ||
	    row.supplier ||
	    !row.production_item) {
		return;
	}

	// Fetch default supplier for this item
	frappe.call({
		method: 'ujwal_industries.api.subcontracting_suppliers.get_default_subcontracting_suppliers',
		args: {
			items: [row.production_item],
			company: frm.doc.company
		},
		callback: function(r) {
			if (r.message && row.production_item in r.message) {
				frappe.model.set_value(
					cdt,
					cdn,
					'supplier',
					r.message[row.production_item].supplier
				);
			}
		}
	});
}
