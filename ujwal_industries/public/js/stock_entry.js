frappe.ui.form.on("Stock Entry", {
    refresh(frm) {
        apply_scrap_item_filter(frm);
    },

    custom_is_scrap_entry(frm) {
        apply_scrap_item_filter(frm);
    },

    bom_no(frm) {
        apply_scrap_item_filter(frm);
    }
});

function apply_scrap_item_filter(frm) {
    // Only for Scrap Entries
    if (!frm.doc.custom_is_scrap_entry || !frm.doc.bom_no) {
        return;
    }

    // Fetch Scrap Items from BOM
    frappe.call({
    method:"ujwal_industries.ujwal_industries.overrides.stock_entry.get_bom_scrap_items",
    args: {
        bom_no: frm.doc.bom_no
    },
    callback(r) {
        if (!r.message || !r.message.length) return;

        let allowed_items = r.message;

        frm.fields_dict.items.grid.get_field("item_code").get_query =
            function () {
                return {
                    filters: {
                        name: ["in", allowed_items]
                    }
                };
            };

        frm.doc.items.forEach(row => {
            if (row.item_code && !allowed_items.includes(row.item_code)) {
                frappe.model.set_value(
                    row.doctype,
                    row.name,
                    "item_code",
                    ""
                );
            }
        });
    }
});

}

frappe.ui.form.on("Stock Entry Detail", {
    item_code(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (frm.doc.custom_is_scrap_entry) {
            frappe.model.set_value(cdt, cdn, "is_scrap_item", 1);
        }
    }
});
