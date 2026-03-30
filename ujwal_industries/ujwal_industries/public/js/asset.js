frappe.ui.form.on("Asset", {
	refresh(frm) {
		frm.set_query("asset_category", function () {
			return {
				filters: {
					is_group: 0,
				},
			};
		});

		update_tool_type_field(frm);
	},

	asset_category(frm) {
		update_tool_type_field(frm);
	},
});

function update_tool_type_field(frm) {
	if (!frm.doc.asset_category) {
		set_tool_type_state(frm, false);
		if (frm.doc.tool_type) {
			frm.set_value("tool_type", null);
		}
		return;
	}

	frappe.call({
		method: "ujwal_industries.ujwal_industries.overrides.asset.is_tool_asset_category",
		args: {
			asset_category: frm.doc.asset_category,
		},
		callback: ({ message }) => {
			const usesToolSeries = Boolean(message);
			set_tool_type_state(frm, usesToolSeries);

			if (!usesToolSeries && frm.doc.tool_type) {
				frm.set_value("tool_type", null);
			}
		},
	});
}

function set_tool_type_state(frm, usesToolSeries) {
	frm.toggle_display("tool_type", usesToolSeries);
	frm.toggle_reqd("tool_type", usesToolSeries);
}
