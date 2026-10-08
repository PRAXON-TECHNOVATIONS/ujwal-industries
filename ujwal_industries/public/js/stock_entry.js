frappe.ui.form.on("Stock Entry", {
    refresh(frm) {
        apply_scrap_item_filter(frm);
        fetch_annexure_rates_for_all_rows(frm);
    },

    custom_is_scrap_entry(frm) {
        apply_scrap_item_filter(frm);
    },

    bom_no(frm) {
        apply_scrap_item_filter(frm);
    },

    subcontracting_order(frm) {
        fetch_annexure_rates_for_all_rows(frm);
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
    },

    subcontracted_item(frm, cdt, cdn) {
        // Re-picking the item is a deliberate reset — fetch fresh even if
        // this row's rate was locked from a manual edit before.
        frappe.model.set_value(cdt, cdn, "custom_annexure_rate_locked", 0);
        fetch_annexure_rate(frm, cdt, cdn);
    },

    basic_rate(frm, cdt, cdn) {
        // Only lock on rate edits the USER made — our own fetch sets a guard
        // flag around its own writes so it doesn't lock itself out. This
        // flag is persisted (custom field) so it survives save/reload —
        // otherwise reopening the doc would re-fetch and clobber a rate the
        // user had deliberately typed in during a previous session.
        let row = locals[cdt][cdn];
        if (row.__annexure_setting_rate) return;
        frappe.model.set_value(cdt, cdn, "custom_annexure_rate_locked", 1);
    },

    qty(frm, cdt, cdn) {
        if (!frm.doc.set_basic_rate_manually) return;
        let saved_rate = locals[cdt][cdn].basic_rate;
        setTimeout(() => {
            let current = locals[cdt] && locals[cdt][cdn];
            if (current && current.basic_rate !== saved_rate) {
                frappe.model.set_value(cdt, cdn, "basic_rate", saved_rate);
            }
        }, 800);
    }
});

function fetch_annexure_rate(frm, cdt, cdn) {
    // "Send to Subcontractor" rows: subcontracted_item is the item coming
    // BACK from the subcontractor (e.g. Case Hardened piece), not the raw
    // material physically sent out. Its own default Subcontract row (Item
    // master → Subcontracting Suppliers) says which Operation this shipment
    // is for; the per-piece rate is Net RM Cost/Pc + every operation before
    // that one, from the item's latest submitted Cost Estimation.
    //
    // Once a user has typed their own rate on this row (custom_annexure_rate_locked),
    // this never runs again for it — an auto-fetch has no business silently
    // overwriting a rate someone deliberately corrected, on this save or any
    // later reopen. Re-picking the item clears the lock, since that's a
    // deliberate reset.
    let row = locals[cdt][cdn];
    if (frm.doc.purpose !== "Send to Subcontractor" || !row.subcontracted_item) return;
    if (row.custom_annexure_rate_locked) return;

    frappe.call({
        method: "ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.get_subcontract_annexure_rate",
        args: {
            item_code: row.subcontracted_item,
            company: frm.doc.company,
            subcontracting_order: frm.doc.subcontracting_order
        },
        callback(r) {
            if (!r.message) return;
            let current = locals[cdt] && locals[cdt][cdn];
            if (!current || current.custom_annexure_rate_locked) return;

            current.__annexure_setting_rate = true;
            frappe.model.set_value(cdt, cdn, "set_basic_rate_manually", 1);
            frappe.model.set_value(cdt, cdn, "basic_rate", r.message.rate).then(() => {
                current.__annexure_setting_rate = false;
            });
        }
    });
}

function fetch_annexure_rates_for_all_rows(frm) {
    // Rows brought in via "Get Items From" → Subcontracting Order arrive
    // through a server-side mapper, which doesn't fire the per-row
    // subcontracted_item trigger above — so on load/refresh, sweep every row
    // once per browser session and fetch its rate directly. fetch_annexure_rate
    // itself skips any row already locked by a manual edit.
    if (!frm.doc.__islocal && frm.doc.docstatus !== 0) return;
    if (frm.doc.purpose !== "Send to Subcontractor" || !frm.doc.items || !frm.doc.items.length) return;

    frm.doc.items.forEach(row => {
        if (row.subcontracted_item && !row.__annexure_rate_fetched) {
            row.__annexure_rate_fetched = true;
            fetch_annexure_rate(frm, row.doctype, row.name);
        }
    });
}
