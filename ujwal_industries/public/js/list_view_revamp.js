(function () {
	const PAGE_CLASS = "ujwal-scrollable-list-view";
	const COLUMN_MIN_WIDTH = 120;
	const COLUMN_MAX_WIDTH = 320;
	const META_MIN_WIDTH = 110;
	const META_MAX_WIDTH = 220;
	const SUBJECT_MIN_WIDTH = 160;
	const SALES_ORDER_COLUMNS = [
		{ key: "custom_customer_names", label: __("Customer") },
		{ key: "item_code", label: __("Item Code") },
		{ key: "item_name", label: __("Item Name") },
	];

	function clamp(value, min, max) {
		return Math.max(min, Math.min(max, value));
	}

	function get_measurement_width($el) {
		if (!$el?.length) return 0;
		const node = $el.get(0);
		return Math.ceil(
			Math.max(
				node.scrollWidth || 0,
				$el.outerWidth() || 0,
				($el.text() || "").trim().length * 8
			)
		);
	}

	function apply_width($el, width) {
		if (!$el?.length || !width) return;
		$el.css({
			width: `${width}px`,
			minWidth: `${width}px`,
			maxWidth: `${width}px`,
			flex: `0 0 ${width}px`,
		});
	}

	function reset_width($el) {
		if (!$el?.length) return;
		$el.css({
			width: "",
			minWidth: "",
			maxWidth: "",
			flex: "",
		});
	}

	function align_list_view(listview) {
		if (!listview?.$result?.length || listview.view_name !== "List") return;

		const $pageMain = listview.page?.main;
		if ($pageMain?.length) {
			$pageMain.addClass(PAGE_CLASS);
		}

		const $headerCols = listview.$result.find(".list-row-head .list-header-subject > .list-row-col");
		const $rows = listview.$result.find(".list-row-container .list-row");
		if (!$headerCols.length || !$rows.length) return;

		reset_width($headerCols);
		reset_width(listview.$result.find(".list-row .level-left > .list-row-col"));
		reset_width(listview.$result.find(".list-row-head .level-right, .list-row .level-right"));

		$headerCols.each((index, headerCol) => {
			const $headerCol = $(headerCol);
			const isSubject = $headerCol.hasClass("list-subject");
			let width = get_measurement_width($headerCol) + 24;

			$rows.each((_, row) => {
				const $col = $(row).find(".level-left > .list-row-col").eq(index);
				width = Math.max(width, get_measurement_width($col) + 24);
			});

			width = clamp(width, isSubject ? SUBJECT_MIN_WIDTH : COLUMN_MIN_WIDTH, COLUMN_MAX_WIDTH);
			apply_width($headerCol, width);

			$rows.each((_, row) => {
				apply_width($(row).find(".level-left > .list-row-col").eq(index), width);
			});
		});

		let metaWidth = get_measurement_width(listview.$result.find(".list-row-head .level-right")) + 16;
		$rows.each((_, row) => {
			metaWidth = Math.max(metaWidth, get_measurement_width($(row).find(".level-right")) + 16);
		});
		metaWidth = clamp(metaWidth, META_MIN_WIDTH, META_MAX_WIDTH);

		apply_width(listview.$result.find(".list-row-head .level-right"), metaWidth);
		$rows.each((_, row) => {
			const $right = $(row).find(".level-right");
			apply_width($right, metaWidth);
			$(row)
				.find(".list-row-activity")
				.css({
					width: `${metaWidth}px`,
					minWidth: `${metaWidth}px`,
					justifyContent: "flex-start",
				});
		});
	}

	function get_unique_values(rows, fieldname) {
		return [
			...new Set(
				(rows || [])
					.map((row) => row[fieldname])
					.filter(Boolean)
			),
		];
	}

	function add_sales_order_headers(listview) {
		const $headerLeft = listview.$result.find(".list-row-head .level-left");
		if (!$headerLeft.length) return;

		SALES_ORDER_COLUMNS.forEach((column) => {
			if ($headerLeft.find(`.ujwal-so-extra-col[data-key="${column.key}"]`).length) return;

			$headerLeft.append(
				`<div class="list-row-col ellipsis hidden-xs ujwal-so-extra-col" data-key="${frappe.utils.escape_html(column.key)}">
					<span>${frappe.utils.escape_html(column.label)}</span>
				</div>`
			);
		});
	}

	function add_sales_order_row_columns(listview, salesOrder, values) {
		const $matched = listview.$result
			.find(".list-row-container [data-name], .list-row[data-name]")
			.filter(function () {
				return $(this).attr("data-name") === salesOrder;
			});
		const $row = $matched.hasClass("list-row") ? $matched.first() : $matched.find(".list-row").first();
		const $rowLeft = $row.find(".level-left");
		if (!$rowLeft.length) return;

		SALES_ORDER_COLUMNS.forEach((column) => {
			const value = values[column.key] || "";
			const html = `<span class="ellipsis">${frappe.utils.escape_html(value)}</span>`;
			const $existing = $rowLeft.find(`.ujwal-so-extra-col[data-key="${column.key}"]`);

			if ($existing.length) {
				$existing.html(html);
			} else {
				$rowLeft.append(
					`<div class="list-row-col ellipsis hidden-xs ujwal-so-extra-col" data-key="${frappe.utils.escape_html(column.key)}">
						${html}
					</div>`
				);
			}
		});
	}

	function add_sales_order_columns(listview) {
		if (listview.doctype !== "Sales Order" || !listview?.$result?.length || listview.view_name !== "List") {
			return Promise.resolve();
		}

		const docs = listview.data || [];
		const salesOrders = docs.map((doc) => doc.name).filter(Boolean);
		if (!salesOrders.length) return Promise.resolve();

		return frappe.call({
			method: "ujwal_industries.api.sales_order_tracking.get_so_items_for_list",
			args: { sales_orders: salesOrders },
		}).then((r) => {
			const items = r.message || [];
			const itemsBySalesOrder = {};
			items.forEach((item) => {
				if (!item.parent) return;
				itemsBySalesOrder[item.parent] = itemsBySalesOrder[item.parent] || [];
				itemsBySalesOrder[item.parent].push(item);
			});

			add_sales_order_headers(listview);

			docs.forEach((doc) => {
				const itemsForSalesOrder = itemsBySalesOrder[doc.name] || [];
				add_sales_order_row_columns(listview, doc.name, {
					custom_customer_names: doc.customer_name_ || doc.customer_name || "",
					item_code: get_unique_values(itemsForSalesOrder, "item_code").join(", "),
					item_name: get_unique_values(itemsForSalesOrder, "item_name").join(", "),
				});
			});
		});
	}

	function patch_list_view() {
		if (!frappe?.views?.ListView || frappe.views.ListView.__ujwal_revamp_patched) return;
		frappe.views.ListView.__ujwal_revamp_patched = true;

		const original_after_render = frappe.views.ListView.prototype.after_render;
		frappe.views.ListView.prototype.after_render = function () {
			original_after_render.call(this);
			requestAnimationFrame(() => {
				add_sales_order_columns(this).then(() => align_list_view(this));
			});
		};
	}

	if (frappe?.boot) {
		patch_list_view();
	} else {
		$(document).ready(() => patch_list_view());
	}

	$(window).on(
		"resize",
		frappe.utils.debounce(() => {
			const current_list = cur_list;
			if (current_list?.view_name === "List") {
				align_list_view(current_list);
			}
		}, 150)
	);
})();
