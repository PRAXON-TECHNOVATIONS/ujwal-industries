function set_wip_from_production_item(frm) {
    if (!frm.doc.production_item) {
        return;
    }
    frappe.call({
        method: "ujwal_industries.ujwal_industries.overrides.work_order.set_wip_from_production_item",
        args: {
            production_item: frm.doc.production_item
        },
        callback: function (r) {
            if (r.message) {
                setTimeout(() => {
                    frm.set_value("wip_warehouse", r.message);
                    frm.refresh_field("wip_warehouse");
                }, 300);
            }
        }
    });
}

function render_work_order_progress(frm) {
	const total = flt(frm.doc.qty || 0);
	const produced = flt(frm.doc.produced_qty || 0);
	const transferred = flt(frm.doc.material_transferred_for_manufacturing || 0);
	const in_progress = Math.max(transferred - produced, 0);

	const produced_pct = total ? ((produced / total) * 100).toFixed(2) : "0.00";
	const in_progress_pct = total ? ((in_progress / total) * 100).toFixed(2) : "0.00";

	if (!document.getElementById("production-progress-text")) {
		const firstProgress = document.querySelector(".form-dashboard .progress");
		if (firstProgress) {
			const line = document.createElement("div");
			line.id = "production-progress-text";
			line.className = "text-muted";
			line.style.margin = "5px 0 5px 0";
			line.innerHTML = `
				<b>Production Percentage:</b>
				Produced (${produced_pct}%),
				In Progress (${in_progress_pct}%)
			`;
			firstProgress.after(line);
		}
	}
	setTimeout(() => {
		const bars = document.querySelectorAll(".form-dashboard .progress-bar");

		if (bars.length < 2) {
			return;
		}

		bars[0].setAttribute(
			"title",
			`Produced ${produced} (${produced_pct}%)`
		);
		bars[0].setAttribute("data-bs-toggle", "tooltip");

		bars[1].setAttribute(
			"title",
			`${in_progress} items in progress (${in_progress_pct}%)`
		);
		bars[1].setAttribute("data-bs-toggle", "tooltip");

		let index = 2;

		if (bars[index]) {
			bars[index].setAttribute(
				"title",
				`Working ${working} (${working_pct}%)`
			);
			bars[index].setAttribute("data-bs-toggle", "tooltip");
			index++;
		}

		if (bars[index]) {
			bars[index].setAttribute(
				"title",
				`Completed ${completed} (${completed_pct}%)`
			);
			bars[index].setAttribute("data-bs-toggle", "tooltip");
			index++;
		}

		if (bars[index]) {
			bars[index].setAttribute(
				"title",
				`Not Started ${not_started} (${not_started_pct}%)`
			);
			bars[index].setAttribute("data-bs-toggle", "tooltip");
		}

		if (window.bootstrap) {
			bars.forEach(bar => {
				if (!bootstrap.Tooltip.getInstance(bar)) {
					new bootstrap.Tooltip(bar);
				}
			});
		}
	}, 300);

	frappe.call({
		method: "ujwal_industries.api.work_order_progress.get_job_card_progress",
		args: { work_order: frm.doc.name },
		callback(r) {
			if (!r.message) return;

			const completed = flt(r.message.completed);
			const working = flt(r.message.working);
			const not_started = flt(r.message.not_started);

			const completed_pct = total ? ((completed / total) * 100).toFixed(2) : "0.00";
			const working_pct = total ? ((working / total) * 100).toFixed(2) : "0.00";
			const not_started_pct = total ? ((not_started / total) * 100).toFixed(2) : "0.00";

			const bars = [];

			if (completed > 0) {
				bars.push({
					title: `Completed ${completed} (${completed_pct}%)`,
					width: completed_pct + "%",
					progress_class: "progress-bar-success",
				});
			}

			if (working > 0) {
				bars.push({
					title: `Working ${working} (${working_pct}%),`,
					width: working_pct + "%",
					progress_class: "progress-bar-info"
				});
			}

			if (not_started > 0) {
				bars.push({
					title: `Not Started ${not_started} (${not_started_pct}%)`,
					width: not_started_pct + "%",
					progress_class: "progress-bar-secondary"
				});
			}

			frm.dashboard.add_progress(
				"Job Card Execution Progress",
				bars,
				`<b>Job Cards:</b>
				Completed ${completed} (${completed_pct}%),
				Working ${working} (${working_pct}%),
				Not Started ${not_started} (${not_started_pct}%)`
			);
		}
	});
    frappe.call({
		method: "ujwal_industries.api.work_order_progress.get_operation_progress",
		args: { work_order: frm.doc.name },
		callback(r) {
			if (!r.message) return;
			update_operations_progress_bar(r.message);
		}
	});
}

function update_operations_progress_bar(operation_data) {
	const texts = document.querySelectorAll(".form-dashboard .text-muted");
	let target = null;

	texts.forEach(el => {
		if (el.innerText.startsWith("Pending Operations") || el.innerText.startsWith("Operations")) {
			target = el;
		}
	});

	if (!target) return;

	let parts = [];

	if (operation_data.completed.length) {
		parts.push(
			`Completed: ${operation_data.completed
				.map(o => `${o[0]} (${o[1].toFixed(0)}%)`)
				.join(", ")}`
		);
	}

	if (operation_data.in_progress.length) {
		parts.push(
			`In Progress: ${operation_data.in_progress
				.map(o => `${o[0]} (${o[1].toFixed(0)}%)`)
				.join(", ")}`
		);
	}

	if (operation_data.on_hold.length) {
		parts.push(
			`On Hold: ${operation_data.on_hold
				.map(o => `${o[0]} (${o[1].toFixed(0)}%)`)
				.join(", ")}`
		);
	}
	if (operation_data.not_started.length) {
		parts.push(
			`Not Started: ${operation_data.not_started
				.map(o => `${o[0]} (${o[1].toFixed(0)}%)`)
				.join(", ")}`
		);
	}
	target.innerHTML = `<b>Operations:</b> ${parts.join(", ")}`;

    setTimeout(() => {
		const progressBars = document.querySelectorAll(
			".form-dashboard .progress"
		);

		//  2nd progress bar = Operations Bar
		const operationProgress = progressBars[1];

		const bars = operationProgress.querySelectorAll(".progress-bar");
		if (!bars.length) return;

		const tooltips = [];

		operation_data.completed.forEach(o => {
			tooltips.push(`Completed: ${o[0]} (${o[1].toFixed(0)}%)`);
		});

		operation_data.in_progress.forEach(o => {
			tooltips.push(`In Progress: ${o[0]} (${o[1].toFixed(0)}%)`);
		});

		operation_data.on_hold.forEach(o => {
			tooltips.push(`On Hold: ${o[0]} (${o[1].toFixed(0)}%)`);
		});

		operation_data.not_started.forEach(o => {
			tooltips.push(`Not Started: ${o[0]} (${o[1].toFixed(0)}%)`);
		});

		bars.forEach((bar, index) => {
			if (!tooltips[index]) return;

			bar.setAttribute("title", tooltips[index]);
			bar.setAttribute("data-bs-toggle", "tooltip");

			if (window.bootstrap && !bootstrap.Tooltip.getInstance(bar)) {
				new bootstrap.Tooltip(bar);
			}
		});
	}, 400);
}

frappe.ui.form.on("Work Order", {
	production_item(frm) {
        set_wip_from_production_item(frm);
    },

    refresh(frm) {
    if (frm.doc.docstatus !== 1) return;
	render_work_order_progress(frm);

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

                    // Work Order base qty
                    let wo_qty = flt(frm.doc.qty);
                    let produced_qty = flt(frm.doc.produced_qty);

                    frappe.call({
                        method: "frappe.client.get_value",
                        args: {
                            doctype: "Item",
                            filters: { name: frm.doc.production_item },
                            fieldname: "custom_tolerance_",
                        },
                    }).then((r) => {
                        let tolerance_pct = flt(r?.message?.custom_tolerance_ || 0);

                        // TOTAL max allowed (WO qty + tolerance)
                        let total_max_qty =
                            wo_qty + ((wo_qty * tolerance_pct) / 100);

                        // Remaining allowed considering already produced
                        let max_qty = total_max_qty - produced_qty;

                        if (max_qty <= 0) {
                            frappe.throw(__("All quantity already produced"));
                        }

                        if (input_qty > max_qty) {
                            frappe.throw(
                                __(
                                    "Qty cannot be more than {0} (Produced: {1}, Tolerance: {2}%)",
                                    [max_qty, produced_qty, tolerance_pct]
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

// ============================================================================
// Total Process Time Calculation
// ============================================================================
frappe.ui.form.on('Work Order', {
    onload(frm) {
        if (!frm.is_new()) {
            calculate_and_show_process_time(frm);
        }
    },

    refresh(frm) {
        if (!frm.is_new()) {
            calculate_and_show_process_time(frm);
        }

        // Original scrap tracking code
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

// ============================================================================
// Custom Batch Size Override
// ============================================================================
/**
 * Override Work Order functions to use custom_batchsize instead of batch_size.
 * This ensures ujwal_industries custom field works throughout manufacturing.
 */

frappe.ui.form.on('Work Order Operation', {
	custom_batchsize: function(frm, cdt, cdn) {
		// When custom_batchsize changes, sync to batch_size for compatibility
		let row = locals[cdt][cdn];
		if (row.custom_batchsize && 'batch_size' in row) {
			frappe.model.set_value(cdt, cdn, 'batch_size', row.custom_batchsize);
		}
	},

	batch_size: function(frm, cdt, cdn) {
		// When batch_size changes (from BOM copy), sync to custom_batchsize
		let row = locals[cdt][cdn];
		if (row.batch_size && !row.custom_batchsize) {
			frappe.model.set_value(cdt, cdn, 'custom_batchsize', row.batch_size);
		}
	}
});

// ============================================================================
// Total Process Time Calculation
// ============================================================================
/**
 * Calculate and display total process time for Work Order
 * Time calculated from Work Order creation to final Manufacture completion
 * Includes: Material Transfer time, Job Card execution time, Manufacture time
 */
function calculate_and_show_process_time(frm) {
	frappe.call({
		method: "ujwal_industries.api.work_order_process_time.get_process_time",
		args: {
			work_order: frm.doc.name
		},
		callback(r) {
			if (!r.message) return;

			const data = r.message;

			// Add indicator for total process time
			if (data.total_time_hours) {
				frm.dashboard.add_indicator(
					__("Total Process Time: {0}", [data.total_time_formatted]),
					data.status_color
				);
			}

			// Add detailed timeline if available
			if (data.timeline && data.timeline.length > 0) {
				show_process_timeline(frm, data);
			}
		}
	});
}

function show_process_timeline(frm, data) {
	const timeline_html = `
		<div class="process-timeline" style="margin: 15px 0; padding: 15px; background: #f8f9fa; border-radius: 5px;">
			<h5 style="margin-bottom: 10px; color: #5e64ff;">
				<i class="fa fa-clock-o"></i> Process Timeline
			</h5>
			<table class="table table-bordered table-sm" style="background: white;">
				<thead>
					<tr>
						<th style="width: 30%">Stage</th>
						<th style="width: 25%">Start Time</th>
						<th style="width: 25%">End Time</th>
						<th style="width: 20%; text-align: right;">Duration</th>
					</tr>
				</thead>
				<tbody>
					${data.timeline.map(item => `
						<tr>
							<td><strong>${item.stage}</strong></td>
							<td>${item.start_time || '-'}</td>
							<td>${item.end_time || '-'}</td>
							<td style="text-align: right;">${item.duration || '-'}</td>
						</tr>
					`).join('')}
				</tbody>
				<tfoot>
					<tr style="background: #e9ecef; font-weight: bold;">
						<td colspan="3">Total Process Time</td>
						<td style="text-align: right;">${data.total_time_formatted}</td>
					</tr>
				</tfoot>
			</table>
		</div>
	`;

	// Add to form sidebar or create a custom section
	if (!frm.fields_dict.custom_process_timeline) {
		// If custom field doesn't exist, add to page
		frm.dashboard.$wrapper.append(timeline_html);
	} else {
		frm.fields_dict.custom_process_timeline.$wrapper.html(timeline_html);
	}
}