// Copyright (c) 2026, Ujjwal Aggrawal and contributors
// For license information, please see license.txt

// frappe.query_reports["GRN Processing TIme"] = {
// 	"filters": [

// 	]
// };

frappe.query_reports["GRN Processing Time"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            // reqd: 1,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            // reqd: 1,
        },
        {
            fieldname: "purchase_receipt",
            label: __("Purchase Receipt"),
            fieldtype: "Link",
            options: "Purchase Receipt",
        },
    ],

    tree: true,
    initial_depth: 0,

    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (!data) return value;

        // Parent row bold
        if (data.indent === 0) {
            value = `<b>${value}</b>`;
        }

        // Delay color coding
        if (column.fieldname === "delay_days") {
            const delay = Number(data.delay_days || 0);

            if (delay <= 0) {
                value = `<span style="color:#28a745;font-weight:600;">${delay}</span>`;
            } else {
                value = `<span style="color:#dc3545;font-weight:600;">${delay}</span>`;
            }
        }

        return value;
    },
};
