frappe.ui.form.on('Purchase Receipt', {
    refresh: function(frm) {
        toggle_rate_amount_visibility(frm);
    },

    onload: function(frm) {
        toggle_rate_amount_visibility(frm);
    },

    setup: function(frm) {
        toggle_rate_amount_visibility(frm);
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

