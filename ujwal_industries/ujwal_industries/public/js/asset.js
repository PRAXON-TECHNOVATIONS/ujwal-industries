frappe.ui.form.on("Asset", {
	refresh(frm) {
		frm.set_query("asset_category", function () {
			return {
				filters: {
					is_group: 0,
				},
			};
		});
	},
});
