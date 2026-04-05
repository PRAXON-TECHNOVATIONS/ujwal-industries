function toggle_subcontracting_supplier_fields(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const show_per_day_qty =
		Number(frm.doc.is_sub_contracted_item || 0) === 1 &&
		Number(row.is_per_day_qty_based || 0) === 1;
	const grid = frm.fields_dict.custom_subcontracting_suppliers.grid;
	const grid_row = grid.grid_rows_by_docname[cdn];

	if (grid_row && grid_row.grid_form) {
		grid_row.grid_form.fields_dict.per_day_qty.df.hidden = show_per_day_qty ? 0 : 1;
		grid_row.grid_form.fields_dict.lead_time_days.df.hidden = show_per_day_qty ? 1 : 0;
		grid_row.grid_form.layout.refresh_sections();
	}

	grid.update_docfield_property('per_day_qty', 'hidden', show_per_day_qty ? 0 : 1);
	grid.update_docfield_property('lead_time_days', 'hidden', show_per_day_qty ? 1 : 0);
	frm.refresh_field('custom_subcontracting_suppliers');
}

function toggle_all_subcontracting_supplier_rows(frm) {
	(frm.doc.custom_subcontracting_suppliers || []).forEach(row => {
		toggle_subcontracting_supplier_fields(frm, row.doctype, row.name);
	});
}

frappe.ui.form.on('Item', {
	refresh: function (frm) {
		toggle_all_subcontracting_supplier_rows(frm);
	},
	is_sub_contracted_item: function (frm) {
		toggle_all_subcontracting_supplier_rows(frm);
	},
	custom_subcontracting_suppliers_add: function (frm, cdt, cdn) {
		toggle_subcontracting_supplier_fields(frm, cdt, cdn);
	}
});

frappe.ui.form.on('Item Subcontracting Supplier', {
	is_per_day_qty_based: function (frm, cdt, cdn) {
		toggle_subcontracting_supplier_fields(frm, cdt, cdn);
	},
	form_render: function (frm, cdt, cdn) {
		toggle_subcontracting_supplier_fields(frm, cdt, cdn);
	}
});
