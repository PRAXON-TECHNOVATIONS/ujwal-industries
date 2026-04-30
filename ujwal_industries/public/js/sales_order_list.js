(function () {
	const EXTRA_COLUMNS = [
		{ key: 'custom_customer_names', label: __('Customer') },
		{ key: 'item_code', label: __('Item Code') },
		{ key: 'item_name', label: __('Item Name') },
	];

frappe.listview_settings['Sales Order'] = frappe.listview_settings['Sales Order'] || {};
	frappe.listview_settings['Sales Order'].add_fields = [
		...new Set([
			...(frappe.listview_settings['Sales Order'].add_fields || []),
			'customer',
			'customer_name',
			'customer_name_',
		]),
	];

	const original_refresh = frappe.listview_settings['Sales Order'].refresh;
	frappe.listview_settings['Sales Order'].refresh = function (listview) {
		if (original_refresh) {
			original_refresh(listview);
		}
		requestAnimationFrame(() => render_sales_order_extra_columns(listview));
	};

	function render_sales_order_extra_columns(listview) {
		if (!listview?.$result?.length || listview.view_name !== 'List') {
			return;
		}

		const docs = listview.data || [];
		const sales_orders = docs.map((doc) => doc.name).filter(Boolean);
		if (!sales_orders.length) {
			return;
		}

		Promise.all([
			// Use whitelisted Python API to reliably fetch child table rows
			frappe.call({
				method: 'ujwal_industries.api.sales_order_tracking.get_so_items_for_list',
				args: { sales_orders: sales_orders },
			}).then((r) => r.message || []),
			frappe.db.get_list('Sales Order', {
				filters: { name: ['in', sales_orders] },
				fields: ['name', 'customer', 'customer_name', 'customer_name_'],
				limit_page_length: sales_orders.length,
			}),
		]).then(([items, sales_order_rows]) => {
			const items_by_so = {};
			(items || []).forEach((item) => {
				if (item.parent) {
					items_by_so[item.parent] = items_by_so[item.parent] || [];
					items_by_so[item.parent].push(item);
				}
			});

			const sales_order_by_name = {};
			const customers = [];
			(sales_order_rows || []).forEach((row) => {
				sales_order_by_name[row.name] = row;
				if (row.customer) customers.push(row.customer);
			});

			const unique_customers = [...new Set(customers)];
			const customer_query = unique_customers.length
				? frappe.db.get_list('Customer', {
					filters: { name: ['in', unique_customers] },
					fields: ['name', 'custom_customer_names', 'customer_name'],
					limit_page_length: unique_customers.length,
				})
				: Promise.resolve([]);

			customer_query.then((customer_rows) => {
				const customer_by_name = {};
				(customer_rows || []).forEach((row) => {
					customer_by_name[row.name] = row;
				});

				add_headers(listview);

				docs.forEach((doc) => {
					const so_row = sales_order_by_name[doc.name] || doc;
					const customer_row = customer_by_name[so_row.customer] || {};
					const items_for_so = items_by_so[doc.name] || [];
					const values = {
						custom_customer_names: customer_row.custom_customer_names || so_row.customer_name_ || so_row.customer_name || customer_row.customer_name || '',
						item_code: get_unique_values(items_for_so, 'item_code').join(', '),
						item_name: get_unique_values(items_for_so, 'item_name').join(', '),
					};
					add_row_columns(listview, doc.name, values);
				});

				if (frappe.views.ListView.__ujwal_revamp_patched) {
					requestAnimationFrame(() => $(window).trigger('resize'));
				}
			});
		});
	}

	function get_unique_values(rows, fieldname) {
		return [...new Set((rows || []).map((r) => r[fieldname]).filter(Boolean))];
	}

	function add_headers(listview) {
		const $header_left = listview.$result.find('.list-row-head .level-left');
		if (!$header_left.length || $header_left.find('.ujwal-so-extra-col').length) {
			return;
		}
		EXTRA_COLUMNS.forEach((column) => {
			$header_left.append(
				`<div class="list-row-col ellipsis hidden-xs ujwal-so-extra-col" data-key="${frappe.utils.escape_html(column.key)}">
					<span>${frappe.utils.escape_html(column.label)}</span>
				</div>`
			);
		});
	}

	function add_row_columns(listview, sales_order, values) {
		// data-name may be on .list-row-container or on .list-row depending on Frappe version
		const $elem = listview.$result.find('[data-name]').filter(function () {
			return $(this).attr('data-name') === sales_order;
		}).first();

		if (!$elem.length) return;

		let $row_left = $elem.find('.level-left').first();
		if (!$row_left.length) {
			$row_left = $elem.closest('.list-row, .list-row-container').find('.level-left').first();
		}
		if (!$row_left.length) return;

		EXTRA_COLUMNS.forEach((column) => {
			const value = values[column.key] || '';
			const $existing = $row_left.find(`.ujwal-so-extra-col[data-key="${column.key}"]`);
			const html = `<span class="ellipsis">${frappe.utils.escape_html(value)}</span>`;

			if ($existing.length) {
				$existing.html(html);
				return;
			}

			$row_left.append(
				`<div class="list-row-col ellipsis hidden-xs ujwal-so-extra-col" data-key="${frappe.utils.escape_html(column.key)}">
					${html}
				</div>`
			);
		});
	}
})();
