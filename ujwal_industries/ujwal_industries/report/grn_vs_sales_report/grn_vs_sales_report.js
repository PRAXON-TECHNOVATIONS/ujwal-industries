// Copyright (c) 2026, Ujjwal Aggrawal and contributors
// For license information, please see license.txt

frappe.query_reports["GRN Vs Sales Report"] = {
	filters: [
		{
            fieldname: "purchase_receipt",
            label: __("Purchase Receipt"),
            fieldtype: "Link",
            options: "Purchase Receipt",
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

        if (data.indent === 0) {
            value = `<b>${value}</b>`;
        }
        
        return value;
    },
};
