(function () {
	frappe.listview_settings['Sales Order'] = frappe.listview_settings['Sales Order'] || {};

	function add_quick_filter(listview, { label, filter_doctype, filter_fieldname, fieldtype, options, condition }) {
		// Append into the same .standard-filter-section as the built-in filters
		// (ID, Customer, Date, Delivery Status, Billing Status) instead of the
		// default page_form, so this field continues that row left-to-right
		// instead of landing in a separate block next to the Filter/Sort buttons.
		const $standard_filter_section = listview.page.page_form.find('.standard-filter-section');
		const field = listview.page.add_field({
			fieldtype: fieldtype || 'Data',
			options: options,
			fieldname: filter_fieldname,
			doctype: filter_doctype,
			condition: condition || 'like',
			label: __(label),
		}, $standard_filter_section.length ? $standard_filter_section : undefined);

		if (fieldtype === 'Link') {
			field.df.change = () => listview.filter_area.debounced_refresh_list_view();
		} else {
			field.$input.on('input', () => listview.filter_area.debounced_refresh_list_view());
		}
	}

	function remove_standard_filter(listview, fieldname) {
		const field = listview.page.fields_dict && listview.page.fields_dict[fieldname];
		if (!field) return;
		$(field.wrapper).remove();
		delete listview.page.fields_dict[fieldname];
	}

	const _orig_onload = frappe.listview_settings['Sales Order'].onload;
	frappe.listview_settings['Sales Order'].onload = function (listview) {
		if (_orig_onload) _orig_onload(listview);

		// Marker class so the filter-bar grid CSS below only applies here, not
		// to every list view's page_form.
		listview.page.page_form.addClass('ujwal-so-filter-grid');

		// Customer Name is redundant with Customer, and Company is rarely filtered
		// on here — drop both so Item Code / Customer's PO No fit cleanly in the
		// filter bar instead of wrapping into a misaligned row.
		remove_standard_filter(listview, 'customer_name');
		remove_standard_filter(listview, 'company');

		add_quick_filter(listview, {
			label: 'Item Code',
			filter_doctype: 'Sales Order Item',
			filter_fieldname: 'item_code',
			fieldtype: 'Link',
			options: 'Item',
			condition: '=',
		});

		add_quick_filter(listview, {
			label: "Customer's PO No",
			filter_doctype: 'Sales Order',
			filter_fieldname: 'po_no',
		});

		const $btn = listview.page.add_button(
			__('Create Bulk Pre Production'),
			function () {
				const selected = listview.get_checked_items();
				if (!selected.length) return;

				frappe.model.with_doctype('Bulk Pre Production Plan', function () {
					const new_doc = frappe.model.get_new_doc('Bulk Pre Production Plan');
					new_doc.company = frappe.defaults.get_default('company') || '';

					selected.forEach(function (row) {
						const child = frappe.model.add_child(
							new_doc, 'Bulk PP Sales Order', 'sales_orders'
						);
						child.sales_order = row.name;
					});

					frappe.set_route('Form', 'Bulk Pre Production Plan', new_doc.name);
				});
			},
			{ btn_class: 'btn-primary' }
		);

		$btn.hide();

		listview.$result.on(
			'change',
			'.list-row-checkbox, .list-select-all',
			function () {
				if (listview.get_checked_items().length > 0) {
					$btn.show();
				} else {
					$btn.hide();
				}
			}
		);
	};

	// NOTE: The Item Code / Item Name extra columns (and their header/row alignment)
	// are rendered by list_view_revamp.js, which patches ListView.after_render and
	// also handles the scrollable layout. Don't duplicate that logic here or the
	// columns get inserted twice and fight the alignment pass.
})();
