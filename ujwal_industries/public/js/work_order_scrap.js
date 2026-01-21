frappe.ui.form.on('Work Order', {
    refresh(frm) {
        if (!frm.doc.name) return;

        // ✅ correct HTML field check
        if (!frm.fields_dict.custom_scrap_tracking) {
            console.warn("Custom Scrap Tracking HTML field not found");
            return;
        }

        frappe.call({
            method: "ujwal_industries.api.scrap_dashboard.get_work_order_scrap_status",
            args: {
                work_order: frm.doc.name
            },
            callback(r) {
                if (!r.message || !r.message.length) {
                    frm.fields_dict.custom_scrap_tracking.$wrapper.html(
                        "<p>No Scrap Data Found</p>"
                    );
                    return;
                }
                render_scrap_table(frm, r.message);
            }
        });
    }
});


function render_scrap_table(frm, data) {
    let html = `
        <h4>Scrap Tracking</h4>
        <table class="table table-bordered">
            <thead>
                <tr>
                    <th>Scrap Item</th>
                    <th>Stock Entry</th>
                    <th>Expected Qty</th>
                    <th>Manufactured Qty</th>
                    <th>Actual Scrap Qty</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.forEach(row => {
        let color =
            row.status === "Fully Received" ? "green" :
            row.status === "Partial Received" ? "orange" : "red";

        html += `
            <tr>
                <td>${row.scrap_item_code ? row.scrap_item_code + " - " + row.scrap_item_name : row.scrap_item_name}</td>
                <td>${row.stock_entry || ""}</td>
                <td>${row.expected_scrap_qty}</td>
                <td>${row.completed_qty || ""}</td>
                <td>${row.actual_scrap_qty}</td>
                <td style="color:${color}; font-weight:bold;">
                    ${row.status}
                </td>
            </tr>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    frm.fields_dict.custom_scrap_tracking.$wrapper.html(html);
}
