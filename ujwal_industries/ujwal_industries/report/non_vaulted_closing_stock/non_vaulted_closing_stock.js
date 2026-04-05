// Copyright (c) 2026, Ujjwal Aggrawal and contributors
// For license information, please see license.txt

frappe.query_reports["Non Vaulted Closing Stock"] = {
	filters: [
		{
            fieldname: "item",
            label: __("Item"),
            fieldtype: "Link",
            options: "Item",
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
};
