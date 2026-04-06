frappe.query_reports["BOM Stock Tree Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "bom",
			label: __("BOM"),
			fieldtype: "Link",
			options: "BOM",
			get_query: function () {
				const company = frappe.query_report.get_filter_value("company");
				return {
					filters: {
						docstatus: 1,
						is_active: 1,
						...(company ? { company } : {}),
					},
				};
			},
		},
		{
			fieldname: "item",
			label: __("FG / SFG Item"),
			fieldtype: "Link",
			options: "Item",
			get_query: function () {
				return {
					filters: {
						is_stock_item: 1,
					},
				};
			},
		},
		{
			fieldname: "warehouses",
			label: __("Warehouses"),
			fieldtype: "MultiSelectList",
			get_data: function (txt) {
				const company = frappe.query_report.get_filter_value("company");
				return frappe.call({
					method: "frappe.desk.search.search_link",
					args: {
						doctype: "Warehouse",
						txt,
						filters: {
							disabled: 0,
							...(company ? { company } : {}),
						},
						page_length: 1000,
					},
				}).then((r) => {
					return (r.message || []).map((row) => {
						if (typeof row === "string") return row;
						return row.value || row.description || row.name;
					});
				});
			},
		},
		{
			fieldname: "max_depth",
			label: __("Max Depth"),
			fieldtype: "Int",
			default: 10,
		},
	],

	tree: true,
	initial_depth: 2,

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!data) return value;

		if (data.indent === 0) {
			value = `<span style="font-weight:700;">${value}</span>`;
		}

		if (data.row_type === "FG" && column.fieldname === "item_code") {
			value = `<span style="font-weight:600;color:#1f6feb;">${value}</span>`;
		}

		if (data.row_type === "SFG" && column.fieldname === "row_type") {
			value = `<span style="color:#0a7f5a;font-weight:600;">${value}</span>`;
		}

		if (data.row_type === "Scrap" && (column.fieldname === "row_type" || column.fieldname === "item_code")) {
			value = `<span style="color:#c0392b;font-weight:600;">${value}</span>`;
		}

		if (column.fieldname === "warehouse_breakup" && data.warehouse_breakup) {
			value = `<div title="${frappe.utils.escape_html(
				data.warehouse_breakup
			)}" style="white-space:normal;line-height:1.4;font-size:12px;">${frappe.utils.escape_html(
				data.warehouse_breakup
			)}</div>`;
		}

		return value;
	},
};
