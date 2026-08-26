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
        fetch_annexure_rate(frm, cdt, cdn);
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
    let row = locals[cdt][cdn];
    if (frm.doc.purpose !== "Send to Subcontractor" || !row.subcontracted_item) return;

    frappe.call({
        method: "ujwal_industries.ujwal_industries.doctype.cost_estimation.cost_estimation.get_subcontract_annexure_rate",
        args: {
            item_code: row.subcontracted_item,
            company: frm.doc.company,
            subcontracting_order: frm.doc.subcontracting_order
        },
        callback(r) {
            if (!r.message) return;
            let rate = r.message.rate;
            frappe.model.set_value(cdt, cdn, "set_basic_rate_manually", 1);
            frappe.model.set_value(cdt, cdn, "basic_rate", rate);
            // ERPNext's own qty/conversion_factor handlers kick off an async
            // get_incoming_rate call (valuation-based) that overwrites
            // basic_rate whenever a row's qty is set — including when rows
            // are bulk-inserted by the Get Items From mapper, which races
            // with this fetch. Re-assert after it's had time to land, same
            // defensive pattern as the existing qty() handler in this file.
            setTimeout(() => {
                let current = locals[cdt] && locals[cdt][cdn];
                if (current && current.basic_rate !== rate) {
                    frappe.model.set_value(cdt, cdn, "basic_rate", rate);
                }
            }, 1200);
        }
    });
}

function fetch_annexure_rates_for_all_rows(frm) {
    // Rows brought in via "Get Items From" → Subcontracting Order arrive
    // through a server-side mapper, which doesn't fire the per-row
    // subcontracted_item trigger above — so on load/refresh, sweep every row
    // and fetch its rate directly. Runs for every such row regardless of
    // whatever basic_rate is currently sitting there (including 0 or a stale
    // valuation-rate fallback ERPNext may have already written in) — only
    // skipped once the row is already flagged as manually rate-set AND has a
    // rate, meaning a user has knowingly overridden it since.
    if (!frm.doc.__islocal && frm.doc.docstatus !== 0) return;
    if (frm.doc.purpose !== "Send to Subcontractor" || !frm.doc.items || !frm.doc.items.length) return;

    frm.doc.items.forEach(row => {
        if (row.subcontracted_item && !row.__annexure_rate_fetched) {
            row.__annexure_rate_fetched = true;
            fetch_annexure_rate(frm, row.doctype, row.name);
        }
    });
}
