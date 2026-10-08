
frappe.query_reports["BOM Tool Report"] = {
	filters: [
		{
			fieldname: "item",
			label: __("FG Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "tool",
			label: __("Tool"),
			fieldtype: "Link",
			options: "Asset",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (data.indent === 0 || data.indent === 1) {
			value = `<b>${value}</b>`;
		}

		if (column.fieldname === "status" && data.status) {
			let color = "";
			switch (data.status) {
				case "Ready for Production":
					color = "#49ba0c";
					break;
				case "Production Completed":
					color = "#f0c929";
					break;
				case "Under Maintenance":
					color = "#f64848";
					break;
			}
			value = `<span style="color:${color}; font-weight:600;">
                        ${data.status}
                     </span>`;
		}

		return value;
	},
};
