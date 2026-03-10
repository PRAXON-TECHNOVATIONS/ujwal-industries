frappe.ui.form.on('BOM', {
    refresh: function(frm) {
        set_operation_filter(frm);
    },
});

function set_operation_filter(frm) {

    frm.set_query("operation", "custom_tool_details", function(doc, cdt, cdn) {

        let operation_list = [];

        if (doc.operations) {
            doc.operations.forEach(function(row) {
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

frappe.ui.form.on("BOM Operation", {
    form_render(frm, cdt, cdn) {

        let row = locals[cdt][cdn];
        let grid_row = frm.fields_dict.operations.grid.grid_rows_by_docname[cdn];

        if (!grid_row.grid_form) return;

        let wrapper = $(grid_row.grid_form.fields_dict.custom_machine.wrapper);
        wrapper.empty();

        let control = frappe.ui.form.make_control({
            parent: wrapper,
            df: {
                fieldtype: "MultiSelectList",
                placeholder: "Select Workstations",

                get_data: function(txt) {
                    return frappe.db.get_link_options("Workstation", txt);
                },

                change: function() {

                    let values = control.get_value() || [];

                    // ensure default workstation always exists
                    if (row.workstation && !values.includes(row.workstation)) {
                        values.unshift(row.workstation);
                        control.set_value(values);
                    }

                    frappe.model.set_value(
                        cdt,
                        cdn,
                        "custom_workstations_csv",
                        values.join(",")
                    );

                    frm.dirty();
                }
            },
            render_input: true
        });

        control.refresh();

        let values = [];

        if (row.custom_workstations_csv) {
            values = row.custom_workstations_csv.split(",");
        }

        // auto insert default workstation
        if (row.workstation && !values.includes(row.workstation)) {
            values.unshift(row.workstation);
        }

        control.set_value(values);

    }
});