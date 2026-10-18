// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.query_reports["PO Submission Delay"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: ["", "Pending", "Submitted"] },
		{ fieldname: "from_date", label: __("Generated From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Generated To"), fieldtype: "Date" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "submitted_by", label: __("Submitted By"), fieldtype: "Link", options: "User" },
		{ fieldname: "min_delay_days", label: __("Delay at least (Days)"), fieldtype: "Float" },
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === "status") {
			const color = data.status === "Pending" ? "orange" : "green";
			value = `<span class="indicator-pill ${color}">${value}</span>`;
		}
		// Pending delay keeps growing — highlight it
		if (column.fieldname === "delay_days" && data.status === "Pending") {
			value = `<span style="color: var(--red-600); font-weight: 600;">${value}</span>`;
		}
		return value;
	},
};
