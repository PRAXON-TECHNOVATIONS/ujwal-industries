frappe.ui.form.on("Work Order", {
    refresh(frm) {
    if (erpnext?.work_order && !erpnext.work_order._qty_prompt_overridden) {
    erpnext.work_order._qty_prompt_overridden = true;

    erpnext.work_order.show_prompt_for_qty_input = function (frm, purpose) {
        let max = this.get_max_transferable_qty(frm, purpose);

        let fields = [
            {
                fieldtype: "Float",
                label: __("Qty for {0}", [__(purpose)]),
                fieldname: "qty",
                description: __("Max: {0}", [max]),
                default: max,
            },
            {
                fieldtype: "Check",
                label: __("Consider Process Loss"),
                fieldname: "consider_process_loss",
                default: 0,
                onchange() {
                    if (this.value) {
                        frm.qty_prompt.set_value(
                            "qty",
                            max - (frm.doc.process_loss_qty || 0)
                        );
                    } else {
                        frm.qty_prompt.set_value("qty", max);
                    }
                },
            },
        ];

        if (purpose === "Disassemble") {
            fields.push({
                fieldtype: "Link",
                options: "Warehouse",
                fieldname: "target_warehouse",
                label: __("Target Warehouse"),
                default: frm.doc.source_warehouse || frm.doc.wip_warehouse,
                get_query() {
                    return {
                        filters: {
                            company: frm.doc.company,
                            is_group: 0,
                        },
                    };
                },
            });
        }

        return new Promise((resolve) => {
            frm.qty_prompt = frappe.prompt(
                fields,
                (data) => {

                    data.purpose = purpose;

                    let input_qty = flt(data.qty);
                    let remaining_qty = flt(frm.doc.qty - frm.doc.produced_qty);

                    if (remaining_qty <= 0) {
                        frappe.throw(__("All quantity already produced"));
                    }

                    frappe
                        .call({
                            method: "frappe.client.get_value",
                            args: {
                                doctype: "Item",
                                filters: { name: frm.doc.production_item },
                                fieldname: "custom_tolerance_",
                            },
                        })
                        .then((r) => {
                            let tolerance_pct = flt(r?.message?.custom_tolerance_ || 0);
                            let tol_qty = (remaining_qty * tolerance_pct) / 100;

                            let max_qty = remaining_qty;

                            if (tolerance_pct > 0) {
                                max_qty = remaining_qty + tol_qty;
                            }
                            if (input_qty > max_qty) {
                                frappe.throw(
                                    __(
                                        "Qty cannot be more than {0} (Remaining: {1}, Tolerance: {2}%)",
                                        [
                                            max_qty,
                                            remaining_qty,
                                            tolerance_pct,
                                        ]
                                    )
                                );
                            }
                            resolve(data);
                        });
                },
                __("Select Quantity"),
                __("Create")
            );
        });
    };
}
}
});

frappe.ui.form.on('Work Order', {
    refresh(frm) {
        if (frm.fields_dict.custom_scrap_tracking) {
            frm.fields_dict.custom_scrap_tracking.$wrapper.empty();
        }
        if (frm.is_new()) {
            return;
        }

        frappe.call({
            method: "ujwal_industries.api.scrap_dashboard.get_work_order_scrap_status",
            args: {
                work_order: frm.doc.name
            },
            callback(r) {
                if (!r.message || !r.message.length) {
                    frm.fields_dict.custom_scrap_tracking.$wrapper.html(`
                        <div class="text-muted" style="padding: 10px;">
                            Scrap tracking not started yet.
                        </div>
                    `);
                    return;
                }
                let valid_rows = r.message.filter(row => {
                    return row.stock_entry || row.actual_scrap_qty > 0 || row.expected_scrap_qty > 0;
                });

                if (!valid_rows.length) {
                    frm.fields_dict.custom_scrap_tracking.$wrapper.html(`
                        <div class="text-muted" style="padding: 10px;">
                            Scrap tracking not started yet.
                        </div>
                    `);
                    return;
                }
                render_scrap_table(frm, valid_rows);
            }
        });
    }
});

function render_scrap_table(frm, data) {
    let html = `
        <div style="margin-bottom: 15px;">
            <h4>Scrap Tracking</h4>
        </div>
        <table class="table table-bordered table-sm">
            <thead style="background-color: #f8f9fa;">
                <tr>
                    <th style="width: 25%">Scrap Item</th>
                    <th style="width: 15%">Stock Entry</th>
                    <th style="width: 12%; text-align: right;">Expected Qty</th>
                    <th style="width: 15%; text-align: right;">Manufactured Qty</th>
                    <th style="width: 15%; text-align: right;">Actual Scrap Qty</th>
                    <th style="width: 15%">Status</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.forEach(row => {
        // Color Logic
        let color = "red"; // Default Not Received
        if (row.status === "Fully Received") {
            color = "green";
        } else if (row.status === "Partial Received") {
            color = "orange";
        }

        // Bold row for Total
        let is_total = row.scrap_item_name.includes("TOTAL");
        let row_style = is_total ? "font-weight: bold; background-color: #f0f0f0;" : "";

        html += `
            <tr style="${row_style}">
                <td>${row.scrap_item_code ? row.scrap_item_code + " - " + row.scrap_item_name : row.scrap_item_name}</td>
                <td>${row.stock_entry || ""}</td>
                <td style="text-align: right;">${row.expected_scrap_qty}</td>
                <td style="text-align: right;">${row.completed_qty || 0}</td>
                <td style="text-align: right;">${row.actual_scrap_qty}</td>
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