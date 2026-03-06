// Production Plan list view — "Export to Importer" action button
// Allows user to select one or more Production Plans and open them in the
// Production Plan Importer for batch date/supplier editing.

frappe.listview_settings["Production Plan"] = frappe.listview_settings["Production Plan"] || {};

const _orig_onload_pp_list = frappe.listview_settings["Production Plan"].onload;

frappe.listview_settings["Production Plan"].onload = function (listview) {
	if (_orig_onload_pp_list) _orig_onload_pp_list(listview);

	listview.page.add_action_item(__("Export to Importer"), function () {
		const selected = listview.get_checked_items();
		if (!selected.length) {
			frappe.show_alert({
				message: __("Please select at least one Production Plan."),
				indicator: "orange",
			});
			return;
		}

		const pp_names = selected.map((r) => r.name);

		frappe.call({
			method: "ujwal_industries.ujwal_industries.overrides.pp_mr_dates.create_importer_from_selection",
			args: { pp_names: JSON.stringify(pp_names) },
			freeze: true,
			freeze_message: __("Creating importer…"),
			callback(r) {
				if (r.message && r.message.name) {
					frappe.set_route("Form", "Production Plan Importer", r.message.name);
				}
			},
		});
	});
};
