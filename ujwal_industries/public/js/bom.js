frappe.ui.form.on('BOM', {
    refresh: function (frm) {
        // Change Log is populated server-side (ujwal_industries.overrides.bom_change_log)
        // by diffing the whole doc on every save, so it stays a read-only audit trail here.
        let grid = frm.get_field("change_log").grid;
        grid.wrapper.find('.grid-add-row').hide();
        grid.wrapper.find('.grid-add-multiple-rows').hide();
        grid.cannot_add_rows = true;

        set_operation_filter(frm);
    },
    
    setup: function(frm) {
        frappe.call({
            method: "ujwal_industries.overrides.bom.get_tools_under_category",
            callback: function (r) {
                frm.fields_dict.custom_tool_details.grid.get_field('tool').get_query = function(doc, cdt, cdn) {
                return {
                    filters: {
                        asset_category: ["in", r.message]
                    }
                };
            };
            }

        })

        // Tools/Machines (is_fixed_asset = 1) are never actual BOM material or
        // scrap items — exclude them here so Item search stays limited to real
        // RM/SFG/FG items, and route through our own item_query so Part Number
        // search (custom_part_number) still works.
        frm.set_query("item", function () {
            return {
                query: "ujwal_industries.api.link_queries.item_query",
                filters: {
                    is_stock_item: 1,
                    is_fixed_asset: 0,
                },
            };
        });

        frm.set_query("item_code", "items", function () {
            return {
                query: "ujwal_industries.api.link_queries.item_query",
                filters: {
                    include_item_in_manufacturing: 1,
                    is_fixed_asset: 0,
                },
            };
        });

        frm.set_query("item_code", "scrap_items", function () {
            return {
                query: "ujwal_industries.api.link_queries.item_query",
                filters: {
                    is_fixed_asset: 0,
                },
            };
        });
    }
});

function set_operation_filter(frm) {
    frm.set_query("operation", "custom_tool_details", function (doc) {
        let operation_list = [];

        if (doc.operations) {
            doc.operations.forEach(function (row) {
                if (row.operation) {
                    operation_list.push(row.operation);
                }
            });
        }

        return {
            filters: {
                name: ["in", operation_list.length ? operation_list : [""]]
            }
        };
    });
}

function sync_machine_selection(cdt, cdn, values) {
    let row = locals[cdt][cdn];
    values = (values || []).map(value => value && value.trim()).filter(value => value);

    let csv_value = values.join(",");
    let count_value = values.length;
    let current_csv = (row.custom_workstations_csv || "").trim();
    let current_count = Number(row.custom_machine_count || 0);

    if (current_csv === csv_value && current_count === count_value) {
        return;
    }

    frappe.model.set_value(cdt, cdn, "custom_workstations_csv", csv_value);
    frappe.model.set_value(cdt, cdn, "custom_machine_count", count_value);
}

function operation_has_tool(frm, operation) {
    return (frm.doc.custom_tool_details || []).some(row => row.operation === operation && row.tool);
}

frappe.ui.form.on("BOM Operation", {
    form_render(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        let grid_row = frm.fields_dict.operations.grid.grid_rows_by_docname[cdn];

        if (!grid_row.grid_form) return;

        let wrapper = $(grid_row.grid_form.fields_dict.custom_machine.wrapper);
        wrapper.empty();

        let is_initializing = false;
        let control = frappe.ui.form.make_control({
            parent: wrapper,
            df: {
                fieldtype: "MultiSelectList",
                placeholder: "Select Workstations",
                get_data: function (txt) {
                    return frappe.db.get_link_options("Workstation", txt);
                },
                change: function () {
                    if (is_initializing) {
                        return;
                    }

                    let values = control.get_value() || [];
                    sync_machine_selection(cdt, cdn, values);
                }
            },
            render_input: true
        });

        control.refresh();

        let values = [];
        if (row.custom_workstations_csv) {
            values = row.custom_workstations_csv
                .split(",")
                .map(value => value.trim())
                .filter(value => value);
        }

        if (row.workstation && !values.includes(row.workstation)) {
            values.unshift(row.workstation);
        }

        is_initializing = true;
        control.set_value(values);
        is_initializing = false;
    },
    custom_fixed_lot_capacity(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        if (!operation_has_tool(frm, row.operation) || Number(row.custom_fixed_lot_capacity || 0) === 0) {
            return;
        }

        frappe.model.set_value(cdt, cdn, "custom_fixed_lot_capacity", 0);
        frappe.throw(`Lot Capacity cannot be defined for Operation <b>${row.operation}</b> because a Tool is linked to it.`);
    }
});

