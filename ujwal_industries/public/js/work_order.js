frappe.ui.form.on("Work Order", {
	setup(frm) {
		// Tools/Machines (is_fixed_asset = 1) are never a Work Order's FG item or a
		// required raw material — exclude them, and route through our own
		// item_query so Part Number search (custom_part_number) works here too.
		frm.set_query("production_item", function () {
			return {
				query: "ujwal_industries.api.link_queries.item_query",
				filters: {
					is_stock_item: 1,
					is_fixed_asset: 0,
				},
			};
		});

		frm.set_query("item_code", "required_items", function () {
			return {
				query: "ujwal_industries.api.link_queries.item_query",
				filters: {
					is_fixed_asset: 0,
				},
			};
		});
	},
});
