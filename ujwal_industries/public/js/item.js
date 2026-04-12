// ─── Subcontracting Supplier helpers ──────────────────────────────────────────

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

// ─── Material Type helpers ─────────────────────────────────────────────────────

/**
 * Install a lazy get_query on item_group.
 *
 * Root cause: item_group's df.link_filters = '[[...is_group=0...]]' (set in
 * ERPNext's Item doctype JSON). Frappe's ControlLink calls apply_link_field_filters()
 * on every dropdown open, which OVERWRITES get_query with the df.link_filters value —
 * rendering any JS set_query call useless.
 *
 * Fix: clear df.link_filters so apply_link_field_filters() is skipped, then set
 * a single lazy get_query that reads frm.doc.custom_material_type at open-time.
 * setTimeout(0) ensures we run after ERPNext's refresh set_query call.
 */
function install_item_group_query(frm) {
	setTimeout(() => {
		const field = frm.fields_dict['item_group'];
		// Clear the hardcoded link_filters so it doesn't stomp our get_query
		field.df.link_filters = '';
		field.get_query = () => {
			if (!frm.doc.custom_material_type) {
				return { filters: { is_group: 0 } };
			}
			return {
				filters: {
					parent_item_group: frm.doc.custom_material_type,
					is_group: 0
				}
			};
		};
	}, 0);
}

// ─── Item form events ──────────────────────────────────────────────────────────

frappe.ui.form.on('Item', {
	refresh(frm) {
		install_item_group_query(frm);
		toggle_all_subcontracting_supplier_rows(frm);
	},

	item_code(frm) {
		if (frm.doc.item_code && !frm.doc.custom_material_type) {
			frappe.show_alert({
				message: __('Please select a Material Type before setting the Item Code.'),
				indicator: 'red'
			}, 6);
		}
	},

	custom_material_type(frm) {
		// Clear stale item_group whenever material type changes
		if (frm.doc.item_group) {
			frm.set_value('item_group', '');
		}
		// get_query already reads frm.doc dynamically — no re-registration needed
	},

	is_sub_contracted_item(frm) {
		toggle_all_subcontracting_supplier_rows(frm);
	},

	custom_subcontracting_suppliers_add(frm, cdt, cdn) {
		toggle_subcontracting_supplier_fields(frm, cdt, cdn);
	}
});

// ─── Item Subcontracting Supplier child table events ──────────────────────────

frappe.ui.form.on('Item Subcontracting Supplier', {
	is_per_day_qty_based(frm, cdt, cdn) {
		toggle_subcontracting_supplier_fields(frm, cdt, cdn);
	},
	form_render(frm, cdt, cdn) {
		toggle_subcontracting_supplier_fields(frm, cdt, cdn);
	}
});
