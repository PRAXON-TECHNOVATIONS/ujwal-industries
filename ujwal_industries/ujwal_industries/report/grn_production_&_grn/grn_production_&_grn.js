// Copyright (c) 2026, Ujjwal Aggrawal and contributors
// For license information, please see license.txt

frappe.query_reports["GRN Production & GRN"] = {
	filters: [
		{
            fieldname: "material_request",
            label: __("Material Request"),
            fieldtype: "Link",
            options: "Material Request",
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
