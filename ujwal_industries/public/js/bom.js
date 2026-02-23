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