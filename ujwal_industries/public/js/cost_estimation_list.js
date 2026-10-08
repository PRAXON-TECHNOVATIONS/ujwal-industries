(function () {
	frappe.listview_settings['Cost Estimation'] = frappe.listview_settings['Cost Estimation'] || {};

	const _orig_onload = frappe.listview_settings['Cost Estimation'].onload;
	frappe.listview_settings['Cost Estimation'].onload = function (listview) {
		if (_orig_onload) _orig_onload(listview);

		// Replace the "Part Name" filter (item_name only) with the item field
		// itself, routed through our own item_query — it matches item_code
		// (ID), item_name, and Part Number (custom_part_number) all in one
		// box, and excludes Tools/Machines.
		const name_field = listview.page.fields_dict && listview.page.fields_dict['item_name'];
		if (name_field) {
			$(name_field.wrapper).remove();
			delete listview.page.fields_dict['item_name'];
		}

		// Append into the same .standard-filter-section as the ID filter,
		// so this field sits right after ID and before the Filter/Sort
		// controls instead of landing at the far right of the page_form.
		const $standard_filter_section = listview.page.page_form.find('.standard-filter-section');
		const field = listview.page.add_field({
			fieldtype: 'Link',
			options: 'Item',
			fieldname: 'item',
			doctype: 'Cost Estimation',
			condition: '=',
			label: __('Item'),
		}, $standard_filter_section.length ? $standard_filter_section : undefined);
		field.get_query = () => ({
			query: 'ujwal_industries.api.link_queries.item_query',
			filters: {
				is_fixed_asset: 0,
			},
		});
		field.df.change = () => listview.filter_area.debounced_refresh_list_view();
	};
})();
