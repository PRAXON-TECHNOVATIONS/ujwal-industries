frappe.ui.form.on("Production Plan", {
	setup(frm) {
		// Tools/Machines (is_fixed_asset = 1) never belong in the Raw Materials
		// table — exclude them, and route through our own item_query so Part
		// Number search (custom_part_number) works here too.
		frm.set_query("item_code", "mr_items", function () {
			return {
				query: "ujwal_industries.api.link_queries.item_query",
				filters: {
					is_fixed_asset: 0,
				},
			};
		});

		frm.set_query("item_code", "po_items", function () {
			return {
				query: "ujwal_industries.api.link_queries.item_query",
				filters: {
					is_stock_item: 1,
					is_fixed_asset: 0,
				},
			};
		});
	},
});
