// Copyright (c) 2026, Ujwal Industries and contributors
// For license information, please see license.txt

frappe.query_reports["Work Order Stock Entries"] = {
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
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
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
			fieldname: "work_order",
			label: __("Work Order"),
			fieldtype: "Link",
			options: "Work Order",
			get_query: function () {
				return {
					filters: {
						docstatus: 1,
					},
				};
			},
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
			options: ["", "Not Started", "In Process", "Completed", "Stopped", "Closed"],
		},
	],

	// Tree structure settings
	tree: true,
	initial_depth: 1,

	// Custom formatter for tree structure and highlighting
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!data) return value;

		// Make parent rows (Work Order summary) bold
		if (data.indent === 0) {
			value = $(`<span>${value}</span>`);
			var $value = $(value).css("font-weight", "bold");
			value = $value.wrap("<p></p>").parent().html();
		}

		// Highlight scrap items in red
		if (column.fieldname === "item_code" || column.fieldname === "item_name") {
			if (data.is_scrap) {
				value = $(`<span>${value}</span>`);
				var $value = $(value).css("color", "red");
				value = $value.wrap("<p></p>").parent().html();
			}
		}

		// Highlight scrap qty in red
		if (column.fieldname === "scrap_qty" && data.scrap_qty > 0) {
			value = $(`<span>${value}</span>`);
			var $value = $(value).css("color", "red");
			value = $value.wrap("<p></p>").parent().html();
		}

		// Color code purpose
		if (column.fieldname === "purpose" && data.purpose) {
			let color = "";
			switch (data.purpose) {
				case "Material Transfer for Manufacture":
					color = "#2490ef"; // Blue
					break;
				case "Manufacture":
					color = "#28a745"; // Green
					break;
				case "Material Consumption for Manufacture":
					color = "#6c757d"; // Gray
					break;
				default:
					if (data.purpose.includes("Scrap")) {
						color = "#dc3545"; // Red
					}
			}
			if (color) {
				value = $(`<span>${value}</span>`);
				var $value = $(value).css("color", color);
				value = $value.wrap("<p></p>").parent().html();
			}
		}

		return value;
	},

	// Add summary button
	onload: function (report) {
		report.page.add_inner_button(__("Show Summary"), function () {
			show_summary(report);
		});
	},
};

function show_summary(report) {
	const data = report.data;
	if (!data || data.length === 0) {
		frappe.msgprint(__("No data to display"));
		return;
	}

	// Filter only parent rows (Work Orders) for summary
	const work_order_data = data.filter((row) => row.indent === 0);

	if (work_order_data.length === 0) {
		frappe.msgprint(__("No Work Order data to display"));
		return;
	}

	// Calculate totals
	let total_qty_to_produce = 0;
	let total_produced = 0;
	let total_required = 0;
	let total_transferred = 0;
	let total_consumed = 0;
	let total_scrap = 0;

	work_order_data.forEach((row) => {
		total_qty_to_produce += row.qty_to_produce || 0;
		total_produced += row.produced_qty || 0;
		total_required += row.required_qty || 0;
		total_transferred += row.transferred_qty || 0;
		total_consumed += row.consumed_qty || 0;
		total_scrap += row.scrap_qty || 0;
	});

	// Create summary dialog
	const summary_html = `
		<div class="summary-container" style="padding: 15px;">
			<h4 style="margin-bottom: 15px;">${__("Work Order Summary")}</h4>
			<table class="table table-bordered">
				<tbody>
					<tr>
						<td><strong>${__("Total Work Orders")}</strong></td>
						<td>${work_order_data.length}</td>
					</tr>
					<tr>
						<td><strong>${__("Total Qty to Produce")}</strong></td>
						<td>${total_qty_to_produce.toFixed(2)}</td>
					</tr>
					<tr>
						<td><strong>${__("Total Produced Qty")}</strong></td>
						<td>${total_produced.toFixed(2)}</td>
					</tr>
					<tr>
						<td><strong>${__("Total Required Qty (Raw Materials)")}</strong></td>
						<td>${total_required.toFixed(2)}</td>
					</tr>
					<tr>
						<td><strong>${__("Total Transferred Qty")}</strong></td>
						<td>${total_transferred.toFixed(2)}</td>
					</tr>
					<tr>
						<td><strong>${__("Total Consumed Qty")}</strong></td>
						<td>${total_consumed.toFixed(2)}</td>
					</tr>
					<tr style="color: red;">
						<td><strong>${__("Total Scrap Qty")}</strong></td>
						<td>${total_scrap.toFixed(2)}</td>
					</tr>
				</tbody>
			</table>
		</div>
	`;

	const dialog = new frappe.ui.Dialog({
		title: __("Summary"),
		size: "small",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "summary_html",
			},
		],
	});

	dialog.fields_dict.summary_html.$wrapper.html(summary_html);
	dialog.show();
}
