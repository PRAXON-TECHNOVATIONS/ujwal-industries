(function () {
	frappe.listview_settings['BOM'] = frappe.listview_settings['BOM'] || {};

	const _orig_onload = frappe.listview_settings['BOM'].onload;
	frappe.listview_settings['BOM'].onload = function (listview) {
		if (_orig_onload) _orig_onload(listview);

		// The standard "Item" quick filter (from Item.in_standard_filter) has no
		// get_query of its own, so it lists every Item including Tools/Machines
		// (is_fixed_asset = 1). BOMs are never built for those, so exclude them here
		// too, same as the BOM form's item fields.
		const item_field = listview.page.fields_dict && listview.page.fields_dict['item'];
		if (item_field) {
			item_field.get_query = () => ({
				query: 'ujwal_industries.api.link_queries.item_query',
				filters: {
					is_fixed_asset: 0,
				},
			});
		}

		// Always land on "Is Default" = checked whenever the BOM list is freshly
		// opened -- a user can untick it in their session to see every BOM (e.g.
		// two BOMs for the same item with different RM), but the next fresh load
		// (refresh, or navigating back to this list) resets to default-only again.
		// onload only fires once per fresh list instantiation, so this is a forced
		// reset on every load, not something that fights the user mid-session.
		listview.filter_area.add([[listview.doctype, 'is_default', '=', 1]]);
	};
})();
