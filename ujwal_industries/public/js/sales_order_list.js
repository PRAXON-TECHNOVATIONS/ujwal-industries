(function () {
	frappe.listview_settings['Sales Order'] = frappe.listview_settings['Sales Order'] || {};

	const _orig_onload = frappe.listview_settings['Sales Order'].onload;
	frappe.listview_settings['Sales Order'].onload = function (listview) {
		if (_orig_onload) _orig_onload(listview);

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
