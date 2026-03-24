// Copyright (c) 2026, Ujwal Industries and contributors
// Manage Dates — Parallel Planning dialog for Production Plan
// Loaded globally via app_include_js so it is available on the Production Plan form.
// NOTE: This dialog is a static editor — no cascading API calls on field change.
//       All event-driven calculation logic has been intentionally removed pending
//       the parallel-planning context from the product team.

// ============================================================================
// Display helpers
// ============================================================================

function to_date_part(val) {
	if (!val) return '';
	return String(val).slice(0, 10);
}

function to_time_part(val) {
	if (!val) return '';
	const s = String(val);
	return s.length > 10 ? s.slice(11, 16) : '';
}

/** Parse "YYYY-MM-DD HH:MM:SS" → Date (local time). */
function _parse_local_dt(str) {
	if (!str) return null;
	const [date, time] = String(str).split(' ');
	const [y, mo, d]   = (date || '').split('-').map(Number);
	const [h, mn]      = (time || '10:00').split(':').map(Number);
	if (!y || !mo || !d) return null;
	return new Date(y, mo - 1, d, h || 10, mn || 0, 0);
}

/** Format Date → "YYYY-MM-DD HH:MM:00" (local time). */
function _dt_to_str(dt) {
	if (!dt || isNaN(dt.getTime())) return '';
	const p = n => String(n).padStart(2, '0');
	return `${dt.getFullYear()}-${p(dt.getMonth()+1)}-${p(dt.getDate())} ${p(dt.getHours())}:${p(dt.getMinutes())}:00`;
}

function display_dt(val) {
	if (!val) return '<span style="color:#cbd5e1;font-style:italic;">—</span>';
	try { return frappe.datetime.str_to_user(val); } catch(e) { return val; }
}

function esc(v) {
	return frappe.utils.escape_html
		? frappe.utils.escape_html(String(v || ''))
		: String(v || '');
}

// ============================================================================
// Entry point — loads supplier data, then builds the dialog
// ============================================================================

function open_parallel_manage_dates_dialog(frm) {
	if (!(frm.doc.po_items || []).length) {
		frappe.show_alert({ message: __('No FG items available.'), indicator: 'orange' });
		return;
	}

	const _all_item_codes = [
		...(frm.doc.po_items           || []).map(r => r.item_code),
		...(frm.doc.sub_assembly_items || []).map(r => r.production_item),
		...(frm.doc.mr_items           || []).map(r => r.item_code),
	].filter(Boolean);

	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.pp_fg_dates.get_items_suppliers_batch',
		args: { item_codes: JSON.stringify([...new Set(_all_item_codes)]) },
		callback(r) {
			_build_manage_dates_dialog(frm, r.message || {});
		},
	});
}

// ============================================================================
// Dialog builder
// ============================================================================

function _build_manage_dates_dialog(frm, suppliers_by_item) {
	suppliers_by_item = suppliers_by_item || {};

	const po_items  = frm.doc.po_items            || [];
	const sfg_items = frm.doc.sub_assembly_items  || [];
	const mr_items  = frm.doc.mr_items            || [];

	const has_sfg = sfg_items.length > 0;
	const has_mr  = mr_items.length  > 0;

	const ALL_STEPS = [
		{ id: 'fg',  label: 'FG Items',      icon: '1' },
		...(has_sfg ? [{ id: 'sfg', label: 'Sub Assembly', icon: '2' }] : []),
		...(has_mr  ? [{ id: 'mr',  label: 'MR Items',     icon: has_sfg ? '3' : '2' }] : []),
	];

	// ── Chain color palette ────────────────────────────────────────────────
	const SFG_PALETTE = [
		{ dot: '#7c3aed', bg: '#f5f3ff', border: '#c4b5fd', text: '#4c1d95' },  // violet
		{ dot: '#059669', bg: '#f0fdf4', border: '#6ee7b7', text: '#065f46' },  // emerald
		{ dot: '#d97706', bg: '#fffbeb', border: '#fde68a', text: '#78350f' },  // amber
		{ dot: '#dc2626', bg: '#fff1f2', border: '#fecdd3', text: '#881337' },  // rose
		{ dot: '#0284c7', bg: '#f0f9ff', border: '#bae6fd', text: '#0c4a6e' },  // sky
	];

	const sfg_chain_color = {};
	const sfg_chain_label = {};
	po_items.forEach((po, i) => {
		sfg_chain_color[po.name] = SFG_PALETTE[i % SFG_PALETTE.length];
		const so_nums = (po.sales_order || '').replace(/\D/g, '').slice(-5);
		sfg_chain_label[po.name] = String.fromCharCode(65 + i) + (so_nums ? ' · ' + so_nums : '');
	});

	// ── Stepper banner ─────────────────────────────────────────────────────

	function build_stepper_html(active_idx) {
		let steps_html = '';
		ALL_STEPS.forEach((step, i) => {
			const state     = i < active_idx ? 'done' : (i === active_idx ? 'active' : 'pending');
			const circle_bg = state === 'active' ? '#818cf8' : state === 'done' ? '#34d399' : 'rgba(255,255,255,0.15)';
			const label_clr = state === 'active' ? '#e0e7ff' : state === 'done' ? '#a7f3d0' : 'rgba(255,255,255,0.38)';
			const shadow    = state === 'active' ? '0 0 0 4px rgba(129,140,248,0.4)' : 'none';
			const icon      = state === 'done' ? '\u2713' : step.icon;
			const conn_clr  = state === 'done' ? '#34d399' : 'rgba(255,255,255,0.18)';
			const is_last   = i === ALL_STEPS.length - 1;

			steps_html += `
			<div class="md-step-item" data-step-idx="${i}" style="display:flex;align-items:center;gap:10px;flex-shrink:0;">
				<div class="md-step-circle" data-step-idx="${i}" style="width:32px;height:32px;border-radius:50%;background:${circle_bg};color:#fff;
					display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;
					flex-shrink:0;box-shadow:${shadow};">${icon}</div>
				<span class="md-step-label" style="font-size:12px;font-weight:${state === 'active' ? '700' : '500'};
					color:${label_clr};letter-spacing:0.2px;white-space:nowrap;">${step.label}</span>
			</div>`;

			if (!is_last) {
				steps_html += `
			<div class="md-step-connector" style="background:${conn_clr};flex-shrink:0;border-radius:2px;
				width:2px;height:26px;margin:5px 0 5px 15px;"></div>`;
			}
		});

		return `
		<div class="md-sidebar" style="background:linear-gradient(180deg,#1e1b4b 0%,#3730a3 55%,#4f46e5 100%);
			border-radius:10px 0 0 10px;padding:28px 20px 28px 18px;
			display:flex;flex-direction:column;justify-content:flex-start;flex-shrink:0;">
			<div class="md-steps-title" style="color:rgba(255,255,255,0.4);font-size:9px;font-weight:700;
				letter-spacing:1.2px;text-transform:uppercase;margin-bottom:22px;">Steps</div>
			<div class="md-steps-list" style="display:flex;flex-direction:column;">
				${steps_html}
			</div>
		</div>`;
	}

	// ── Step 1: FG table ───────────────────────────────────────────────────

	function build_fg_table() {
		const input_style = `border:1.5px solid #c7d2fe;border-radius:8px;padding:6px 8px;font-size:12px;
			color:#3730a3;background:#fafafe;outline:none;font-family:inherit;
			transition:border-color 0.15s,box-shadow 0.15s;`;

		const rows_html = po_items.map((row, i) => {
			const mfg    = row.custom_manufacturing_type || '';
			const row_bg = i % 2 === 0 ? '#ffffff' : '#f8f7ff';

			const start_date = to_date_part(row.planned_start_date);
			const start_time = to_time_part(row.planned_start_date);
			const end_date   = to_date_part(row.custom_planned_end_date);
			const end_time   = to_time_part(row.custom_planned_end_date);

			return `
			<tr style="background:${row_bg};" data-row-name="${esc(row.name)}">
				<td style="padding:10px 12px;color:#94a3b8;font-size:11px;text-align:center;
					border-bottom:1px solid #f0f0ff;">${i + 1}</td>

				<td style="border-bottom:1px solid #f0f0ff;">
					<div style="font-weight:600;color:#1e1b4b;font-size:13px;">${esc(row.item_code)}</div>
					${row.item_name && row.item_name !== row.item_code
						? `<div style="color:#94a3b8;font-size:11px;margin-top:2px;">${esc(row.item_name)}</div>`
						: ''}
					${row.sales_order
						? `<div style="color:#2563eb;font-size:11px;margin-top:3px;font-weight:600;">SO: ${esc(row.sales_order)}</div>`
						: ''}
					${mfg
						? `<div style="font-size:11px;margin-top:4px;font-weight:600;
								color:${mfg === 'In House' ? '#1e40af' : '#92400e'};">${mfg}</div>`
						: ''}
				</td>

				<td style="padding:10px 14px;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					${row.custom_mfg_days
						? `<div style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_mfg_days)}</div>`
						: ''}
				</td>

				<td style="padding:10px 14px;border-bottom:1px solid #f0f0ff;">
					${row.custom_grn_days
						? `<div style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_grn_days)}</div>`
						: ''}
				</td>

				<td style="padding:10px 14px;border-bottom:1px solid #f0f0ff;">
					${row.custom_pm_days
						? `<div style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_pm_days)}</div>`
						: ''}
				</td>

				<td style="padding:10px 14px;text-align:right;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					<span style="font-weight:600;color:#1e1b4b;font-size:13px;">${row.planned_qty || 0}</span>
					<span style="color:#94a3b8;font-size:11px;margin-left:4px;">${esc(row.stock_uom)}</span>
				</td>

				<!-- PLANNED START (editable) -->
				<td style="padding:10px 14px;border-bottom:1px solid #f0f0ff;">
					<div style="display:flex;gap:6px;align-items:center;">
						<input type="date" class="md-fg-sdate" data-row-name="${esc(row.name)}"
							value="${start_date}" data-original="${start_date}"
							style="${input_style}width:130px;"/>
						<input type="text" class="md-fg-stime" data-row-name="${esc(row.name)}"
							value="${start_time}" data-original="${start_time}"
							placeholder="HH:MM" maxlength="5"
							style="${input_style}width:70px;text-align:center;letter-spacing:1px;
								font-variant-numeric:tabular-nums;font-weight:600;"/>
					</div>
				</td>

				<!-- PLANNED END (editable) -->
				<td style="padding:10px 14px;border-bottom:1px solid #f0f0ff;">
					<div style="display:flex;gap:6px;align-items:center;">
						<input type="date" class="md-fg-edate" data-row-name="${esc(row.name)}"
							value="${end_date}" data-original="${end_date}"
							style="${input_style}width:130px;"/>
						<input type="text" class="md-fg-etime" data-row-name="${esc(row.name)}"
							value="${end_time}" data-original="${end_time}"
							placeholder="HH:MM" maxlength="5"
							style="${input_style}width:70px;text-align:center;letter-spacing:1px;
								font-variant-numeric:tabular-nums;font-weight:600;"/>
					</div>
				</td>
			</tr>`;
		}).join('');

		return `
		<div class="md-table-wrap" style="border:1px solid #e2e8f0;border-radius:10px;overflow:auto;
			box-shadow:0 2px 8px rgba(79,70,229,0.07);-webkit-overflow-scrolling:touch;">
			<table style="border-collapse:collapse;">
				<thead>
					<tr style="background:linear-gradient(90deg,#1e1b4b 0%,#3730a3 100%);">
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:center;">#</th>
						<th style="width:25%;padding:10px 14px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">ITEM</th>
						<th style="width:10%;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">Mfg Days</th>
						<th style="width:10%;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">GRN Days</th>
						<th style="width:10%;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">PM Days</th>
						<th style="width:10%;padding:10px 14px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:right;">QTY</th>
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">PLANNED START ✏</th>
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">PLANNED END ✏</th>
					</tr>
				</thead>
				<tbody>${rows_html}</tbody>
			</table>
		</div>`;
	}

	// ── Step 2: Sub Assembly table ─────────────────────────────────────────

	function build_sfg_table() {
		if (!sfg_items.length) {
			return '<div style="padding:20px;text-align:center;color:#94a3b8;font-style:italic;">No sub-assembly items.</div>';
		}

		const date_inp = `border:1.5px solid #c7d2fe;border-radius:7px;padding:5px 7px;font-size:11px;
			color:#3730a3;background:#fafafe;outline:none;font-family:inherit;
			transition:border-color 0.15s,box-shadow 0.15s;width:112px;`;
		const time_inp = `border:1.5px solid #c7d2fe;border-radius:7px;padding:5px 5px;font-size:11px;
			color:#3730a3;background:#fafafe;outline:none;font-family:inherit;
			transition:border-color 0.15s,box-shadow 0.15s;width:60px;text-align:center;
			letter-spacing:1px;font-variant-numeric:tabular-nums;font-weight:600;`;

		const rows_html = sfg_items.map((row, i) => {
			const chain_id = row.production_plan_item || '';
			const pal      = sfg_chain_color[chain_id] || SFG_PALETTE[0];
			const clabel   = sfg_chain_label[chain_id] || chain_id.slice(-4);

			const mfg     = row.type_of_manufacturing || '';
			const sel_bg  = mfg === 'In House'    ? '#dbeafe' : mfg === 'Subcontract' ? '#fef3c7' : '#dcfce7';
			const sel_clr = mfg === 'In House'    ? '#1e40af' : mfg === 'Subcontract' ? '#92400e' : '#14532d';

			const indent    = row.indent || 0;
			const item_left = indent * 16;
			const tree_chr  = indent > 0 ? `<span style="color:${pal.border};margin-right:3px;">└─</span>` : '';

			const start_date = to_date_part(row.schedule_date);
			const start_time = to_time_part(row.schedule_date);
			const end_date   = to_date_part(row.custom_schedule_end_date);
			const end_time   = to_time_part(row.custom_schedule_end_date);

			return `
			<tr style="border-left:3px solid ${pal.dot};background:${i % 2 === 0 ? '#fff' : '#fafafe'};"
				data-sfg-name="${esc(row.name)}" data-chain="${esc(chain_id)}">

				<td style="padding:8px 10px;color:#94a3b8;font-size:11px;text-align:center;
					border-bottom:1px solid #f0f0ff;">${i + 1}</td>

				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					<div style="display:inline-flex;align-items:center;gap:4px;
						background:${pal.bg};border:1px solid ${pal.border};border-radius:20px;padding:3px 9px;">
						<div style="width:7px;height:7px;border-radius:50%;background:${pal.dot};flex-shrink:0;"></div>
						<span style="font-size:9px;font-weight:700;color:${pal.text};letter-spacing:0.2px;">${esc(clabel)}</span>
					</div>
				</td>

				<td style="padding:8px 14px;border-bottom:1px solid #f0f0ff;">
					<div style="padding-left:${item_left}px;">
						${tree_chr}<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${esc(row.production_item)}</span>
					</div>
					${row.item_name && row.item_name !== row.production_item
						? `<div style="color:#94a3b8;font-size:10px;margin-top:1px;
								padding-left:${item_left + (indent > 0 ? 18 : 0)}px;">${esc(row.item_name)}</div>`
						: ''}
					<div style="margin-top:6px;padding-left:${item_left + (indent > 0 ? 18 : 0)}px;">
						<div style="display:inline-block;padding:2px 8px;border-radius:12px;font-size:10px;font-weight:600;
								background:${sel_bg};color:${sel_clr};">
							${mfg || '—'}
							${mfg === 'Subcontract' && row.supplier ? `
							<br><div style="margin-top:4px;font-size:10px;color:#92400e;background:#fffbeb;
								display:inline-block;padding:2px 6px;border-radius:6px;border:1px solid #fcd34d;">
								${esc(row.supplier)}
							</div>` : ''}
						</div>
					</div>
				</td>

				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;">
					${row.custom_mfg_days
						? `<div style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_mfg_days)}</div>`
						: ''}
				</td>

				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;">
					${row.custom_grn_days
						? `<div style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_grn_days)}</div>`
						: ''}
				</td>

				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;">
					${row.custom_pm_days
						? `<div style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_pm_days)}</div>`
						: ''}
				</td>

				<td style="padding:8px 10px;text-align:right;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${row.qty || 0}</span>
					<span style="color:#94a3b8;font-size:10px;margin-left:3px;">${esc(row.uom || row.stock_uom || '')}</span>
				</td>

				<!-- SCHEDULE START (editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<div style="display:flex;gap:4px;align-items:center;">
						<input type="date" class="md-sfg-sdate" data-sfg-name="${esc(row.name)}"
							value="${start_date}" data-original="${start_date}" style="${date_inp}"/>
						<input type="text" class="md-sfg-stime" data-sfg-name="${esc(row.name)}"
							value="${start_time}" data-original="${start_time}"
							placeholder="HH:MM" maxlength="5" style="${time_inp}"/>
					</div>
				</td>

				<!-- SCHEDULE END (editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<div style="display:flex;gap:4px;align-items:center;">
						<input type="date" class="md-sfg-edate" data-sfg-name="${esc(row.name)}"
							value="${end_date}" data-original="${end_date}" style="${date_inp}"/>
						<input type="text" class="md-sfg-etime" data-sfg-name="${esc(row.name)}"
							value="${end_time}" data-original="${end_time}"
							placeholder="HH:MM" maxlength="5" style="${time_inp}"/>
					</div>
				</td>
			</tr>`;
		}).join('');

		const chain_legend_html = po_items.map((po, i) => {
			const pal = SFG_PALETTE[i % SFG_PALETTE.length];
			const lbl = sfg_chain_label[po.name] || '';
			return `
			<div style="display:inline-flex;align-items:center;gap:5px;
				background:${pal.bg};border:1px solid ${pal.border};border-radius:12px;padding:3px 10px;">
				<div style="width:7px;height:7px;border-radius:50%;background:${pal.dot};"></div>
				<span style="font-size:10px;font-weight:700;color:${pal.text};">Chain ${esc(lbl)}</span>
			</div>`;
		}).join('');

		return `
		<div style="display:flex;align-items:center;justify-content:space-between;
			margin-bottom:14px;flex-wrap:wrap;gap:8px;">
			<div style="display:flex;align-items:center;gap:10px;">
				<div style="width:5px;height:24px;background:linear-gradient(180deg,#4f46e5,#7c3aed);
					border-radius:3px;flex-shrink:0;"></div>
				<div>
					<div style="font-size:15px;font-weight:700;color:#1e1b4b;line-height:1.2;">Sub Assembly Items</div>
					<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Edit schedule dates per chain</div>
				</div>
			</div>
			<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
				${chain_legend_html}
				<span style="background:linear-gradient(135deg,#ede9fe,#ddd6fe);color:#5b21b6;
					padding:4px 14px;border-radius:20px;font-size:12px;font-weight:700;
					box-shadow:0 1px 3px rgba(91,33,182,0.15);white-space:nowrap;">
					${sfg_items.length} item${sfg_items.length !== 1 ? 's' : ''}
				</span>
			</div>
		</div>
		<div class="md-table-wrap" style="border:1px solid #e2e8f0;border-radius:10px;overflow:auto;
			box-shadow:0 2px 8px rgba(79,70,229,0.07);-webkit-overflow-scrolling:touch;">
			<table style="width:100%;border-collapse:collapse;">
				<thead>
					<tr style="background:linear-gradient(90deg,#1e1b4b 0%,#3730a3 100%);">
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:center;">#</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">CHAIN</th>
						<th style="width:20%;padding:9px 14px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">ITEM</th>
						<th style="width:10%;padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">Mfg Days</th>
						<th style="width:10%;padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">GRN Days</th>
						<th style="width:10%;padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">PM Days</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:right;">QTY</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">SCHEDULE START ✏</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">SCHEDULE END ✏</th>
					</tr>
				</thead>
				<tbody>${rows_html}</tbody>
			</table>
		</div>`;
	}

	// ── Step 3: MR Items table ─────────────────────────────────────────────

	function build_mr_table() {
		if (!mr_items.length) {
			return '<div style="padding:20px;text-align:center;color:#94a3b8;font-style:italic;">No material request items.</div>';
		}

		const date_inp = `border:1.5px solid #c7d2fe;border-radius:7px;padding:5px 7px;font-size:11px;
			color:#3730a3;background:#fafafe;outline:none;font-family:inherit;
			transition:border-color 0.15s,box-shadow 0.15s;width:118px;`;

		const rows_html = mr_items.map((row, i) => {
			const so_short = (row.sales_order || '').replace(/\D/g, '').slice(-5);
			const so_badge = so_short
				? `<span style="background:#ede9fe;color:#4c1d95;border-radius:10px;padding:2px 8px;
						font-size:9px;font-weight:700;">SO·${esc(so_short)}</span>`
				: '';

			const start_val = row.custom_start_date ? row.custom_start_date.slice(0, 10) : '';
			const sched_val = row.schedule_date     ? row.schedule_date.slice(0, 10)     : '';

			const mr_suppliers = suppliers_by_item[row.item_code] || [];
			const mr_sup_opts  = mr_suppliers.map(s => {
				const sel = row.custom_supplier ? s.supplier === row.custom_supplier : !!s.is_default;
				return `<option value="${esc(s.supplier)}" data-lead="${s.lead_time_days || 0}"
					${sel ? 'selected' : ''}>${esc(s.supplier)}${s.is_default ? ' ★' : ''}</option>`;
			}).join('');

			return `
			<tr style="background:${i % 2 === 0 ? '#fff' : '#fafafe'};" data-mr-name="${esc(row.name)}">

				<td style="padding:8px 10px;color:#94a3b8;font-size:11px;text-align:center;
					border-bottom:1px solid #f0f0ff;width:32px;">${i + 1}</td>

				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					${so_badge}
				</td>

				<td style="padding:8px 14px;border-bottom:1px solid #f0f0ff;min-width:160px;">
					<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${esc(row.item_code)}</span>
					${row.item_name && row.item_name !== row.item_code
						? `<div style="color:#94a3b8;font-size:10px;margin-top:1px;">${esc(row.item_name)}</div>`
						: ''}
				</td>

				<td style="padding:8px 10px;text-align:right;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${row.quantity || 0}</span>
					<span style="color:#94a3b8;font-size:10px;margin-left:3px;">${esc(row.uom || '')}</span>
				</td>

				<!-- Supplier (editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;min-width:160px;">
					<select class="md-mr-supplier" data-mr-name="${esc(row.name)}"
						style="width:100%;border:1.5px solid #fcd34d;border-radius:8px;padding:4px 8px;
							font-size:11px;color:#92400e;background:#fffbeb;outline:none;cursor:pointer;font-family:inherit;">
						<option value="">-- Select Supplier --</option>
						${mr_sup_opts}
					</select>
				</td>

				<!-- Start Date (editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<input type="date" class="md-mr-sdate" data-mr-name="${esc(row.name)}"
						value="${esc(start_val)}" data-original="${esc(start_val)}" style="${date_inp}" />
				</td>

				<!-- Schedule Date (editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<input type="date" class="md-mr-edate" data-mr-name="${esc(row.name)}"
						value="${esc(sched_val)}" data-original="${esc(sched_val)}" style="${date_inp}" />
				</td>
			</tr>`;
		}).join('');

		return `
		<div style="display:flex;align-items:center;justify-content:space-between;
			margin-bottom:14px;flex-wrap:wrap;gap:8px;">
			<div style="display:flex;align-items:center;gap:10px;">
				<div style="width:36px;height:36px;border-radius:50%;
					background:linear-gradient(135deg,#7c3aed,#4f46e5);
					display:flex;align-items:center;justify-content:center;
					box-shadow:0 2px 8px rgba(79,70,229,0.3);flex-shrink:0;">
					<span style="color:#fff;font-size:16px;">📋</span>
				</div>
				<div>
					<div style="font-size:15px;font-weight:700;color:#1e1b4b;line-height:1.2;">Material Request Items</div>
					<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Edit supplier &amp; purchase dates per raw material</div>
				</div>
			</div>
			<span style="background:linear-gradient(135deg,#ede9fe,#ddd6fe);color:#5b21b6;
				padding:4px 14px;border-radius:20px;font-size:12px;font-weight:700;
				box-shadow:0 1px 3px rgba(91,33,182,0.15);white-space:nowrap;">
				${mr_items.length} item${mr_items.length !== 1 ? 's' : ''}
			</span>
		</div>
		<div style="overflow-x:auto;border-radius:10px;border:1px solid #e2e8f0;
			box-shadow:0 1px 6px rgba(79,70,229,0.07);">
			<table style="width:100%;border-collapse:collapse;font-family:inherit;">
				<thead>
					<tr style="background:linear-gradient(90deg,#1e1b4b 0%,#3730a3 100%);">
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:center;">#</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">SO</th>
						<th style="padding:9px 14px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">ITEM</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:right;">QTY</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">SUPPLIER ✏</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">START DATE ✏</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">SCHEDULE DATE ✏</th>
					</tr>
				</thead>
				<tbody>${rows_html}</tbody>
			</table>
		</div>`;
	}

	// ── Assemble dialog HTML ───────────────────────────────────────────────

	const dialog_html = `
	<style>
		@media (max-width: 640px) {
			#md-root .md-layout        { flex-direction: column !important; }
			#md-root .md-sidebar       { flex-direction: row !important; border-radius: 10px 10px 0 0 !important;
			                             padding: 12px 14px !important; align-items: center !important; }
			#md-root .md-steps-title   { display: none !important; }
			#md-root .md-steps-list    { flex-direction: row !important; align-items: center !important;
			                             flex: 1; justify-content: center; }
			#md-root .md-step-item     { flex-direction: column !important; align-items: center !important;
			                             gap: 3px !important; }
			#md-root .md-step-label    { font-size: 9px !important; }
			#md-root .md-step-connector{ width: 22px !important; height: 2px !important; margin: 0 !important; }
			#md-root .md-content       { padding: 12px 10px !important; }
		}
	</style>
	<div id="md-root" style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:2px 0 4px;">
		<div class="md-layout" style="display:flex;border-radius:10px;overflow:hidden;
			box-shadow:0 2px 12px rgba(79,70,229,0.1);border:1px solid #e2e8f0;margin-bottom:4px;">

			<div id="md-stepper-wrap" style="flex-shrink:0;">
				${build_stepper_html(0)}
			</div>

			<div class="md-content" style="flex:1;padding:20px 18px 16px;min-width:0;">

				<!-- Step FG -->
				<div id="md-step-fg" class="md-step-pane">
					<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:8px;">
						<div style="display:flex;align-items:center;gap:10px;">
							<div style="width:5px;height:24px;background:linear-gradient(180deg,#4f46e5,#7c3aed);border-radius:3px;flex-shrink:0;"></div>
							<div>
								<div style="font-size:15px;font-weight:700;color:#1e1b4b;line-height:1.2;">Finished Goods Items</div>
								<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Edit planned start &amp; end date</div>
							</div>
						</div>
						<span style="background:linear-gradient(135deg,#ede9fe,#ddd6fe);color:#5b21b6;
							padding:4px 14px;border-radius:20px;font-size:12px;font-weight:700;
							box-shadow:0 1px 3px rgba(91,33,182,0.15);white-space:nowrap;">
							${po_items.length} item${po_items.length !== 1 ? 's' : ''}
						</span>
					</div>
					${build_fg_table()}
				</div>

				<!-- Step SFG -->
				<div id="md-step-sfg" class="md-step-pane" style="display:none;">
					${has_sfg ? build_sfg_table() : ''}
				</div>

				<!-- Step MR -->
				<div id="md-step-mr" class="md-step-pane" style="display:none;">
					${has_mr ? build_mr_table() : ''}
				</div>

			</div>
		</div>
	</div>`;

	// ── Create and show dialog ─────────────────────────────────────────────

	const d = new frappe.ui.CustomDialog({
		title: '📅  Reschedule Parallel Production Dates',
		size: 'super-large',
		fields: [{ fieldtype: 'HTML', fieldname: 'content', options: dialog_html }],
		primary_action_label: ALL_STEPS.length > 1 ? __('Next  →') : __('Apply'),
		primary_action() { _go_next(); },
		secondary_action_label: __('← Back'),
		secondary_action() { _go_back(); },
	});

	d.show();

	// ── Step navigation ────────────────────────────────────────────────────

	let _step = 0;

	d.$wrapper.find('.btn-modal-secondary').hide();

	function _go_to_step(idx) {
		_step = Math.max(0, Math.min(idx, ALL_STEPS.length - 1));

		d.$wrapper.find('#md-stepper-wrap').html(build_stepper_html(_step));
		d.$wrapper.find('.md-step-pane').hide();
		d.$wrapper.find(`#md-step-${ALL_STEPS[_step].id}`).show();

		const is_last = (_step === ALL_STEPS.length - 1);
		d.set_primary_action(is_last ? __('Apply') : __('Next  →'), is_last ? _apply_changes : () => _go_next());

		if (_step > 0) {
			d.$wrapper.find('.btn-modal-secondary').show();
		} else {
			d.$wrapper.find('.btn-modal-secondary').hide();
		}
	}

	function _go_next() {
		if (_step < ALL_STEPS.length - 1) _go_to_step(_step + 1);
		else _apply_changes();
	}

	function _go_back() {
		if (_step > 0) _go_to_step(_step - 1);
	}

	// ── Apply changes ──────────────────────────────────────────────────────

	function _apply_changes() {
		const po_data = po_items.map(row => {
			const rn       = row.name;
			const sdate    = d.$wrapper.find(`.md-fg-sdate[data-row-name="${rn}"]`).val();
			const stime    = d.$wrapper.find(`.md-fg-stime[data-row-name="${rn}"]`).val().trim();
			const edate    = d.$wrapper.find(`.md-fg-edate[data-row-name="${rn}"]`).val();
			const etime    = d.$wrapper.find(`.md-fg-etime[data-row-name="${rn}"]`).val().trim();
			const entry    = { name: rn };
			if (sdate) entry.planned_start_date      = `${sdate} ${/^\d{2}:\d{2}$/.test(stime) ? stime : '10:00'}:00`;
			if (edate) entry.custom_planned_end_date = `${edate} ${/^\d{2}:\d{2}$/.test(etime) ? etime : '10:00'}:00`;
			return entry;
		});

		const sfg_data = sfg_items.map(row => {
			const rn        = row.name;
			const sdate_val = d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`).val();
			const stime_val = d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${rn}"]`).val().trim();
			const edate_val = d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${rn}"]`).val();
			const etime_val = d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${rn}"]`).val().trim();
			const entry     = { name: rn };
			if (sdate_val) entry.schedule_date            = `${sdate_val} ${/^\d{2}:\d{2}$/.test(stime_val) ? stime_val : '10:00'}:00`;
			if (edate_val) entry.custom_schedule_end_date = `${edate_val} ${/^\d{2}:\d{2}$/.test(etime_val) ? etime_val : '10:00'}:00`;
			return entry;
		});

		const mr_data = mr_items.map(row => {
			const rn        = row.name;
			const sup_val   = d.$wrapper.find(`.md-mr-supplier[data-mr-name="${rn}"]`).val();
			const sdate_val = d.$wrapper.find(`.md-mr-sdate[data-mr-name="${rn}"]`).val();
			const edate_val = d.$wrapper.find(`.md-mr-edate[data-mr-name="${rn}"]`).val();
			const entry     = { name: rn };
			if (sup_val !== undefined) entry.custom_supplier   = sup_val;
			if (sdate_val)             entry.custom_start_date = sdate_val;
			if (edate_val)             entry.schedule_date     = edate_val;
			return entry;
		});

		const $btn = d.get_primary_btn();
		$btn.prop('disabled', true).text(__('Saving…'));

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_mr_dates.save_managed_dates',
			args: {
				production_plan_name: frm.doc.name,
				po_items_data:        JSON.stringify(po_data),
				sfg_data:             JSON.stringify(sfg_data),
				mr_data:              JSON.stringify(mr_data),
			},
			callback(r) {
				$btn.prop('disabled', false).text(__('Apply'));
				if (r.message && r.message.status === 'ok') {
					frappe.show_alert({ message: __('Production dates saved.'), indicator: 'green' });
					d.hide();
					frm.reload_doc();
				}
			},
			error() {
				$btn.prop('disabled', false).text(__('Apply'));
			},
		});
	}

	// ── Event bindings — UI only (auto-colon + focus ring) ─────────────────

	// Auto-colon on all time inputs
	d.$wrapper.on('input', '.md-fg-stime, .md-fg-etime, .md-sfg-stime, .md-sfg-etime', function() {
		let v = $(this).val().replace(/\D/g, '').slice(0, 4);
		if (v.length >= 3) v = v.slice(0, 2) + ':' + v.slice(2);
		$(this).val(v);
	});

	// Focus ring on FG date/time inputs
	d.$wrapper.on('focusin', '.md-fg-sdate, .md-fg-stime, .md-fg-edate, .md-fg-etime', function() {
		$(this).css({ 'border-color': '#4f46e5', background: '#fff', 'box-shadow': '0 0 0 3px rgba(79,70,229,0.14)' });
	}).on('focusout', '.md-fg-sdate, .md-fg-stime, .md-fg-edate, .md-fg-etime', function() {
		$(this).css({ 'border-color': '#c7d2fe', background: '#fafafe', 'box-shadow': 'none' });
	});

	// Focus ring on SFG date/time inputs
	d.$wrapper.on('focusin', '.md-sfg-sdate, .md-sfg-stime, .md-sfg-edate, .md-sfg-etime', function() {
		$(this).css({ 'border-color': '#4f46e5', background: '#fff', 'box-shadow': '0 0 0 3px rgba(79,70,229,0.14)' });
	}).on('focusout', '.md-sfg-sdate, .md-sfg-stime, .md-sfg-edate, .md-sfg-etime', function() {
		$(this).css({ 'border-color': '#c7d2fe', background: '#fafafe', 'box-shadow': 'none' });
	});

	// Focus ring on MR date inputs
	d.$wrapper.on('focusin', '.md-mr-sdate, .md-mr-edate', function() {
		$(this).css({ 'border-color': '#7c3aed', background: '#fff', 'box-shadow': '0 0 0 3px rgba(124,58,237,0.14)' });
	}).on('focusout', '.md-mr-sdate, .md-mr-edate', function() {
		$(this).css({ 'border-color': '#ddd6fe', background: '#fafafe', 'box-shadow': 'none' });
	});

	// ── Cascade: server-side holiday+shift-aware date recalculation ─────────

	let _cascade_timer = null;

	/**
	 * Fire a debounced cascade API call.
	 * @param {string} row_name   - PP child row name
	 * @param {'start'|'end'} field
	 * @param {string} new_dt     - "YYYY-MM-DD HH:MM:SS"
	 * @param {'fg'|'sfg'|'mr'} row_type
	 */
	function _fire_cascade(row_name, field, new_dt, row_type) {
		if (!row_name || !new_dt) return;
		clearTimeout(_cascade_timer);
		_cascade_timer = setTimeout(() => {
			const $wrap = d.$wrapper;
			$wrap.find('.md-cascade-spinner').remove();
			const $spin = $('<div class="md-cascade-spinner" style="position:fixed;bottom:18px;right:24px;' +
				'background:rgba(79,70,229,0.92);color:#fff;padding:6px 14px;border-radius:20px;' +
				'font-size:12px;font-weight:600;z-index:9999;box-shadow:0 2px 8px rgba(0,0,0,0.18);">' +
				'⟳ Recalculating…</div>').appendTo('body');

			frappe.call({
				method: 'ujwal_industries.ujwal_industries.overrides.pp_mr_dates.recalculate_parallel_cascade',
				args: {
					production_plan_name: frm.doc.name,
					changed_row_name:     row_name,
					changed_field:        field,
					new_value:            new_dt,
					row_type:             row_type,
				},
				callback(r) {
					$spin.remove();
					_apply_cascade_to_dom(r.message || {});
				},
				error() { $spin.remove(); },
			});
		}, 700);
	}

	/** Flash a table row green briefly to indicate it was updated by cascade. */
	function _flash_updated($tr) {
		if (!$tr || !$tr.length) return;
		const orig_bg = $tr.css('background-color');
		$tr.css({ transition: 'background 0.15s', background: '#d1fae5' });
		setTimeout(() => $tr.css({ transition: 'background 0.6s', background: orig_bg || '' }), 800);
	}

	/** Write cascade API results back into the DOM inputs. */
	function _apply_cascade_to_dom(updates) {
		const $wrap = d.$wrapper;
		Object.entries(updates).forEach(([rn, dates]) => {
			// FG row
			const $fg_s = $wrap.find(`.md-fg-sdate[data-row-name="${rn}"]`);
			if ($fg_s.length) {
				if (dates.start) {
					$fg_s.val(dates.start.slice(0, 10));
					$wrap.find(`.md-fg-stime[data-row-name="${rn}"]`).val(
						dates.start.length > 10 ? dates.start.slice(11, 16) : '10:00');
				}
				if (dates.end) {
					$wrap.find(`.md-fg-edate[data-row-name="${rn}"]`).val(dates.end.slice(0, 10));
					$wrap.find(`.md-fg-etime[data-row-name="${rn}"]`).val(
						dates.end.length > 10 ? dates.end.slice(11, 16) : '10:00');
				}
				_flash_updated($wrap.find(`tr[data-row-name="${rn}"]`));
				return;
			}
			// SFG row
			const $sfg_s = $wrap.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`);
			if ($sfg_s.length) {
				if (dates.start) {
					$sfg_s.val(dates.start.slice(0, 10));
					$wrap.find(`.md-sfg-stime[data-sfg-name="${rn}"]`).val(
						dates.start.length > 10 ? dates.start.slice(11, 16) : '10:00');
				}
				if (dates.end) {
					$wrap.find(`.md-sfg-edate[data-sfg-name="${rn}"]`).val(dates.end.slice(0, 10));
					$wrap.find(`.md-sfg-etime[data-sfg-name="${rn}"]`).val(
						dates.end.length > 10 ? dates.end.slice(11, 16) : '10:00');
				}
				_flash_updated($wrap.find(`tr[data-sfg-name="${rn}"]`));
				return;
			}
			// MR row
			if (dates.start) {
				$wrap.find(`.md-mr-sdate[data-mr-name="${rn}"]`).val(dates.start.slice(0, 10));
			}
			if (dates.end) {
				$wrap.find(`.md-mr-edate[data-mr-name="${rn}"]`).val(dates.end.slice(0, 10));
			}
			_flash_updated($wrap.find(`tr[data-mr-name="${rn}"]`));
		});
	}

	/** Build combined datetime string from date + time inputs. */
	function _read_dt($date_el, $time_el) {
		const dv = $date_el.val();
		if (!dv) return null;
		const tv = ($time_el.val() || '').trim();
		const time_str = /^\d{2}:\d{2}$/.test(tv) ? tv : '10:00';
		return `${dv} ${time_str}:00`;
	}

	// FG — start date/time change
	d.$wrapper.on('change', '.md-fg-sdate', function() {
		const rn = $(this).data('row-name');
		const dt = _read_dt($(this), d.$wrapper.find(`.md-fg-stime[data-row-name="${rn}"]`));
		_fire_cascade(rn, 'start', dt, 'fg');
	});
	d.$wrapper.on('blur', '.md-fg-stime', function() {
		const rn = $(this).data('row-name');
		const dt = _read_dt(d.$wrapper.find(`.md-fg-sdate[data-row-name="${rn}"]`), $(this));
		_fire_cascade(rn, 'start', dt, 'fg');
	});

	// FG — end date/time change
	d.$wrapper.on('change', '.md-fg-edate', function() {
		const rn = $(this).data('row-name');
		const dt = _read_dt($(this), d.$wrapper.find(`.md-fg-etime[data-row-name="${rn}"]`));
		_fire_cascade(rn, 'end', dt, 'fg');
	});
	d.$wrapper.on('blur', '.md-fg-etime', function() {
		const rn = $(this).data('row-name');
		const dt = _read_dt(d.$wrapper.find(`.md-fg-edate[data-row-name="${rn}"]`), $(this));
		_fire_cascade(rn, 'end', dt, 'fg');
	});

	// SFG — start date/time change
	d.$wrapper.on('change', '.md-sfg-sdate', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt($(this), d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${rn}"]`));
		_fire_cascade(rn, 'start', dt, 'sfg');
	});
	d.$wrapper.on('blur', '.md-sfg-stime', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt(d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`), $(this));
		_fire_cascade(rn, 'start', dt, 'sfg');
	});

	// SFG — end date/time change
	d.$wrapper.on('change', '.md-sfg-edate', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt($(this), d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${rn}"]`));
		_fire_cascade(rn, 'end', dt, 'sfg');
	});
	d.$wrapper.on('blur', '.md-sfg-etime', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt(d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${rn}"]`), $(this));
		_fire_cascade(rn, 'end', dt, 'sfg');
	});

	// MR — start date change only (end = start + lead_time + grn_days, server computes)
	d.$wrapper.on('change', '.md-mr-sdate', function() {
		const rn = $(this).data('mr-name');
		const dv = $(this).val();
		if (dv) _fire_cascade(rn, 'start', `${dv} 10:00:00`, 'mr');
	});
}
