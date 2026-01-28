frappe.ui.form.on("Stock Entry", {
    custom_is_scrap_entry(frm) {
        if (!frm.doc.custom_is_scrap_entry) return;

        frm.clear_table("items");
        frm.refresh_field("items");

        frm.fields_dict.items.grid.update_docfield_property(
            "is_scrap_item",
            "read_only",
            1
        );
        if (!frm.doc.bom_no) {
            frappe.msgprint(__("Please select BOM first"));
            return;
        }

        frappe.call({
            method: "ujwal_industries.ujwal_industries.overrides.stock_entry.get_bom_scrap_items",
            args: {
                bom_no: frm.doc.bom_no
            },
            callback(r) {
                if (!r.message || !r.message.length) {
                    frappe.msgprint(__("No Scrap Items found in selected BOM"));
                    return;
                }

                let allowed_items = r.message;

                frm.fields_dict.items.grid
                    .get_field("item_code")
                    .get_query = function () {
                        return {
                            filters: {
                                name: ["in", allowed_items]
                            }
                        };
                    };
            }
        });
    }
});

frappe.ui.form.on("Stock Entry Detail", {
    items_add(frm, cdt, cdn) {
        if (!frm.doc.custom_is_scrap_entry) return;
        frappe.model.set_value(cdt, cdn, "is_scrap_item", 1);
    },

    is_scrap_item(frm, cdt, cdn) {
        if (!frm.doc.custom_is_scrap_entry) return;
        frappe.model.set_value(cdt, cdn, "is_scrap_item", 1);
    }
});
