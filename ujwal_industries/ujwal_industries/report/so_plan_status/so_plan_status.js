// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.query_reports["SO Plan Status"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "from_date", label: __("From SO Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To SO Date"), fieldtype: "Date" },
		{ fieldname: "from_delivery_date", label: __("From Delivery Date"), fieldtype: "Date" },
		{ fieldname: "to_delivery_date", label: __("To Delivery Date"), fieldtype: "Date" },
		{
			fieldname: "plan_status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Fully Planned", "Partly Planned", "Not Planned"],
		},
	],

	tree: true,
	initial_depth: 0,

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data || data.indent) return value;

		if (column.fieldname === "plan_status") {
			const color = { "Fully Planned": "red", "Partly Planned": "orange", "Not Planned": "green" }[data.plan_status];
			if (color) value = `<span class="indicator-pill ${color}">${value}</span>`;
		}
		return value;
	},
};
