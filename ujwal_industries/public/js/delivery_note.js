const POSITION_FIELDNAME = "custom_po_no";
const ITEMS_FIELDNAME = "items";
const CHILD_DOCTYPE = "Delivery Note Item";

function set_position_numbers(frm) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const items = frm.doc[ITEMS_FIELDNAME] || [];
	let has_changes = false;

	items.forEach((row, index) => {
		const position_number = String((index + 1) * 10);
		if (!row[POSITION_FIELDNAME]) {
			row[POSITION_FIELDNAME] = position_number;
			has_changes = true;
		}
	});

	if (has_changes) {
		frm.refresh_field(ITEMS_FIELDNAME);
		frm.dirty();
	}
}

frappe.ui.form.on("Delivery Note", {
	setup(frm) {
		set_position_numbers(frm);
	},

	refresh(frm) {
		set_position_numbers(frm);
		toggle_rate_amount_visibility(frm);
	},

	validate(frm) {
		set_position_numbers(frm);
	},

	items_add(frm) {
		set_position_numbers(frm);
	},

	items_remove(frm) {
		set_position_numbers(frm);
	},

	onload: function(frm) {
        toggle_rate_amount_visibility(frm);
    }
});

frappe.ui.form.on(CHILD_DOCTYPE, {
	items_add(frm) {
		set_position_numbers(frm);
	},

	items_move(frm) {
		set_position_numbers(frm);
	},

	items_remove(frm) {
		set_position_numbers(frm);
	},
});



function toggle_rate_amount_visibility(frm) {

     var is_restricted_user = frappe.user_roles.includes('Outsource Store Manager')
                    || frappe.user_roles.includes('Store Incharge');

    var is_privileged = frappe.session.user === 'Administrator'
                    || frappe.user_roles.includes('Administrator')
                    || frappe.user_roles.includes('System Manager');  // ← added

    if (is_restricted_user && !is_privileged) {

        frm.set_df_property('total', 'hidden', 1);
        frm.set_df_property('grand_total', 'hidden', 1);
        frm.set_df_property('rounding_adjustment', 'hidden', 1);
        frm.set_df_property('rounded_total', 'hidden', 1);
        frm.set_df_property('in_words', 'hidden', 1);
        frm.set_df_property('other_charges_calculation', 'hidden', 1);
        frm.set_df_property('gst_breakup_table', 'hidden', 1);
        frm.set_df_property('taxes', 'hidden', 1);
        frm.set_df_property('taxes_and_charges_added', 'hidden', 1);
        frm.set_df_property('taxes_and_charges_deducted', 'hidden', 1);
        frm.set_df_property('total_taxes_and_charges', 'hidden', 1);

        frm.fields_dict.items.grid.update_docfield_property('rate', 'hidden', 1);
        frm.fields_dict.items.grid.update_docfield_property('amount', 'hidden', 1);

        frm.fields_dict.items.grid.update_docfield_property('price_list_rate', 'hidden', 1);
        frm.fields_dict.items.grid.update_docfield_property('base_price_list_rate', 'hidden', 1);

        frm.fields_dict.items.grid.update_docfield_property('base_rate', 'hidden', 1);
        frm.fields_dict.items.grid.update_docfield_property('base_amount', 'hidden', 1);

        frm.fields_dict.items.grid.update_docfield_property('net_rate', 'hidden', 1);
        frm.fields_dict.items.grid.update_docfield_property('net_amount', 'hidden', 1);

        frm.fields_dict.items.grid.update_docfield_property('base_net_rate', 'hidden', 1);
        frm.fields_dict.items.grid.update_docfield_property('base_net_amount', 'hidden', 1);
        frm.fields_dict.items.grid.update_docfield_property('taxable_value', 'hidden', 1);

        frm.refresh_field('items');
    }
}

