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
                            let tolerance_pct = flt(
                                r?.message?.custom_tolerance_ || 0
                            );
                            let tol_qty =
                                (remaining_qty * tolerance_pct) / 100;

                            let min_qty = Math.max(
                                0,
                                remaining_qty - tol_qty
                            );
                            let max_qty = remaining_qty + tol_qty;

                            if (
                                input_qty < min_qty ||
                                input_qty > max_qty
                            ) {
                                frappe.throw(
                                    __(
                                        "Qty must be between {0} and {1} (Remaining: {2}, Tolerance: {3}%)",
                                        [
                                            min_qty,
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
                    frm.fields_dict.custom_scrap_tracking.$wrapper.html(
                        "<p class='text-muted'>No Manufacture Entries Found</p>"
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
        <div class="scrap-title">
            <h4>Scrap Tracking</h4>
        </div>
        <div class="erp-scrap-wrapper">
            <table class="table table-sm erp-scrap-table">
                <thead>
                    <tr>
                        <th width="20%">Scrap Item</th>
                        <th width="15%">Stock Entry</th>
                        <th width="12%">Expected Qty</th>
                        <th width="15%">Manufactured Qty</th>
                        <th width="15%">Actual Scrap Qty</th>
                        <th width="20%">Status</th>
                    </tr>
                </thead>
                <tbody>
    `;

    data.forEach(row => {
        let is_total = row.scrap_item_name.includes("TOTAL");
        let row_class = is_total ? "erp-total-row" : "";

        html += `
                <tr class="${row_class}">
                    <td>${row.scrap_item_code ? row.scrap_item_code + " - " + row.scrap_item_name : row.scrap_item_name}</td>
                    <td>${row.stock_entry || ""}</td>
                    <td>${row.expected_scrap_qty}</td>
                    <td>${row.completed_qty || 0}</td>
                    <td>${row.actual_scrap_qty}</td>
                    <td>
                        <span class="erp-status ${row.status.replaceAll(' ', '-').toLowerCase()}">
                            ${row.status}
                        </span>
                    </td>
                </tr>
        </div>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    frm.fields_dict.custom_scrap_tracking.$wrapper.html(html);
}