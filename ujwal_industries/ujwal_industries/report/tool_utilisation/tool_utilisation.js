
frappe.query_reports["Tool Utilisation"] = {
	filters: [
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

    // tree: true,
    // initial_depth: 0,
    
    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (!data) return value;

        if (data.indent === 0) {
            value = `<b>${value}</b>`;
        }

        if (column.fieldname === "status" && data.status) {
			let color = "";
            switch (data.status) {
                case "Working":
					color = "#49ba0c";
					break;
                case "Maintenance":
                    color = "#2490ef";
					break;

                case "Open":
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
