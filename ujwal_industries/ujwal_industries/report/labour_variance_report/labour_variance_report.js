// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.query_reports["Labour Variance Report"] = {
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
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "job_card",
			label: __("Job Card"),
			fieldtype: "Link",
			options: "Job Card",
		},
		{
			fieldname: "work_order",
			label: __("Work Order"),
			fieldtype: "Link",
			options: "Work Order",
		},
		{
			fieldname: "operation",
			label: __("Operation"),
			fieldtype: "Link",
			options: "Operation",
		},
		{
			fieldname: "workstation",
			label: __("Workstation"),
			fieldtype: "Link",
			options: "Workstation",
		},
		{
			fieldname: "production_item",
			label: __("Production Item"),
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
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				"",
				"Open",
				"Work In Progress",
				"Material Transferred",
				"On Hold",
				"Submitted",
				"Completed",
			],
		},
	],

	// Tree structure settings
	initial_depth: 0,

	// Custom formatter for tree structure and variance highlighting
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Make parent rows (Job Card summary) bold
		if (data && data.indent === 0) {
			value = $(`<span>${value}</span>`);
			var $value = $(value).css("font-weight", "bold");
			value = $value.wrap("<p></p>").parent().html();
		}

		// Highlight variance columns with colors
		if (column.fieldname === "variance_mins" || column.fieldname === "variance_percent") {
			if (data && data[column.fieldname] != null) {
				var variance_value = data[column.fieldname];
				var color = "";

				if (variance_value > 0) {
					// Positive variance (overtime) - Red
					color = "red";
				} else if (variance_value < 0) {
					// Negative variance (undertime) - Green
					color = "green";
				}

				if (color) {
					value = $(`<span>${value}</span>`);
					var $value = $(value).css("color", color);
					value = $value.wrap("<p></p>").parent().html();
				}
			}
		}

		return value;
	},

	// Add chart for visualization
	onload: function (report) {
		report.page.add_inner_button(__("Show Chart"), function () {
			show_variance_chart(report);
		});
	},
};

function show_variance_chart(report) {
	const data = report.data;
	if (!data || data.length === 0) {
		frappe.msgprint(__("No data to display"));
		return;
	}

	// Filter only parent rows (Job Cards) for chart
	const job_card_data = data.filter((row) => row.indent === 0);

	if (job_card_data.length === 0) {
		frappe.msgprint(__("No Job Card data to display"));
		return;
	}

	// Prepare chart data
	const labels = job_card_data.map((row) => row.job_card);
	const expected_times = job_card_data.map((row) => row.expected_time_mins || 0);
	const actual_times = job_card_data.map((row) => row.actual_time_mins || 0);
	const variances = job_card_data.map((row) => row.variance_mins || 0);

	// Create chart dialog
	const chart_dialog = new frappe.ui.Dialog({
		title: __("Labour Variance Chart"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "chart_html",
			},
		],
	});

	chart_dialog.show();

	// Render chart using Frappe Charts
	const chart_wrapper = chart_dialog.fields_dict.chart_html.$wrapper[0];

	new frappe.Chart(chart_wrapper, {
		title: __("Expected vs Actual Time"),
		data: {
			labels: labels,
			datasets: [
				{
					name: __("Expected Time (Mins)"),
					values: expected_times,
				},
				{
					name: __("Actual Time (Mins)"),
					values: actual_times,
				},
				{
					name: __("Variance (Mins)"),
					values: variances,
				},
			],
		},
		type: "bar",
		height: 400,
		colors: ["#7cd6fd", "#743ee2", "#ff5858"],
		barOptions: {
			spaceRatio: 0.5,
		},
		tooltipOptions: {
			formatTooltipY: (d) => d.toFixed(2) + " mins",
		},
	});
}
