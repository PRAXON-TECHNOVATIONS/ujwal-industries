// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.ui.form.on('Item Subcontracting Supplier', {
	// Auto-fill company from global defaults when adding new row
	company: function(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.company) {
			frappe.db.get_default('company').then(default_company => {
				if (default_company) {
					frappe.model.set_value(cdt, cdn, 'company', default_company);
				}
			});
		}
	}
});

// Auto-fill company when row is first added
frappe.ui.form.on('Item', {
	// Override the add row event for custom_subcontracting_suppliers table
	custom_subcontracting_suppliers_add: function(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.company) {
			frappe.db.get_default('company').then(default_company => {
				if (default_company) {
					frappe.model.set_value(cdt, cdn, 'company', default_company);
				}
			});
		}
	}
});
