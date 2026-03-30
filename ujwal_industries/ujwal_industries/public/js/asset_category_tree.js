frappe.treeview_settings["Asset Category"] = {
	fields: [
		{
			fieldtype: "Data",
			fieldname: "asset_category_name",
			label: __("New Asset Category Name"),
			reqd: true,
		},
		{
			fieldtype: "Check",
			fieldname: "is_group",
			label: __("Group Node"),
			description: __("Enable this if this category will contain child categories."),
		},
	],
};
