(function () {
	frappe.listview_settings['Work Order'] = frappe.listview_settings['Work Order'] || {};

	const _orig_onload = frappe.listview_settings['Work Order'].onload;
	frappe.listview_settings['Work Order'].onload = function (listview) {
		if (_orig_onload) _orig_onload(listview);

		// The standard "Item To Manufacture" quick filter (from
		// production_item.in_standard_filter) has no get_query of its own, so it
		// lists every Item including Tools/Machines (is_fixed_asset = 1). Work
		// Orders are never raised for those, so exclude them here too.
		const item_field = listview.page.fields_dict && listview.page.fields_dict['production_item'];
		if (item_field) {
			item_field.get_query = () => ({
				query: 'ujwal_industries.api.link_queries.item_query',
				filters: {
					is_fixed_asset: 0,
				},
			});
		}
	};
})();
