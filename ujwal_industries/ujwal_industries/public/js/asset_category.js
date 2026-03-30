frappe.ui.form.on("Asset Category", {
	setup(frm) {
		frm.set_query("parent_asset_category", function () {
			return {
				filters: {
					is_group: 1,
				},
			};
		});
	},

	refresh(frm) {
		frm.toggle_reqd("accounts", !frm.doc.is_group);
	},

	is_group(frm) {
		frm.toggle_reqd("accounts", !frm.doc.is_group);
	},
});
