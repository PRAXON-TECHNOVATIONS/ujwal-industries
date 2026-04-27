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
			const suppliers_by_item = r.message || {};
			// Fetch item names for FG items (po_items) that may not have item_name stored
			const fg_codes = [...new Set((frm.doc.po_items || []).map(r => r.item_code).filter(Boolean))];
			if (fg_codes.length) {
				frappe.call({
					method: 'frappe.client.get_list',
					args: {
						doctype: 'Item',
						filters: [['name', 'in', fg_codes]],
						fields: ['name', 'item_name'],
						limit_page_length: fg_codes.length + 10,
					},
					callback(ir) {
						const name_map = {};
						(ir.message || []).forEach(i => { name_map[i.name] = i.item_name; });
						(frm.doc.po_items || []).forEach(row => {
							if (!row.item_name) row._fetched_item_name = name_map[row.item_code] || '';
						});
						_build_manage_dates_dialog(frm, suppliers_by_item);
					},
				});
			} else {
				_build_manage_dates_dialog(frm, suppliers_by_item);
			}
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
		...(has_mr  ? [{ id: 'mr',  label: 'MR Items',     icon: '1' }] : []),
		...(has_sfg ? [{ id: 'sfg', label: 'Sub Assembly', icon: has_mr ? '2' : '1' }] : []),
		{ id: 'fg',  label: 'FG Items',      icon: has_mr && has_sfg ? '3' : (has_mr || has_sfg ? '2' : '1') },
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
		const date_inp = `border:1.5px solid #c7d2fe;border-radius:6px;padding:4px 6px;font-size:11px;
			color:#312e81;background:#fafaff;outline:none;font-family:inherit;
			transition:border-color 0.15s,box-shadow 0.15s;width:106px;`;
		const time_inp = `border:1.5px solid #c7d2fe;border-radius:6px;padding:4px 4px;font-size:11px;
			color:#312e81;background:#fafaff;outline:none;font-family:inherit;
			transition:border-color 0.15s,box-shadow 0.15s;width:54px;text-align:center;
			letter-spacing:0.5px;font-variant-numeric:tabular-nums;font-weight:600;`;

		const rows_html = po_items.map((row, i) => {
			const mfg     = row.custom_manufacturing_type || '';
			const mfg_bg  = mfg === 'In House' ? '#dbeafe' : mfg === 'Subcontract' ? '#fef3c7' : '#dcfce7';
			const mfg_clr = mfg === 'In House' ? '#1d4ed8' : mfg === 'Subcontract' ? '#92400e' : '#14532d';
			const row_bg  = i % 2 === 0 ? '#ffffff' : '#f5f3ff';

			const start_date = to_date_part(row.planned_start_date);
			const start_time = to_time_part(row.planned_start_date);
			const end_date   = to_date_part(row.custom_planned_end_date);
			const end_time   = to_time_part(row.custom_planned_end_date);

			const so_short = (row.sales_order || '').replace(/\D/g, '').slice(-5);
			const mfg_d    = row.custom_mfg_days || 0;
			const grn_d    = row.custom_grn_days || 0;
			const pm_d     = row.custom_pm_days  || 0;

			return `
			<tr class="md-fg-row" style="background:${row_bg};" data-row-name="${esc(row.name)}">

				<!-- # -->
				<td style="padding:6px 8px;color:#a5b4fc;font-size:10px;font-weight:700;text-align:center;
					border-bottom:1px solid #ede9fe;width:28px;white-space:nowrap;">${i + 1}</td>

				<!-- Item — all inline, single line -->
				<td style="padding:6px 12px;border-bottom:1px solid #ede9fe;">
					<div style="display:flex;align-items:center;gap:6px;flex-wrap:nowrap;">
						<span style="font-weight:700;color:#1e1b4b;font-size:12px;white-space:nowrap;">${esc(row.item_code)}</span>
						${(row.item_name || row._fetched_item_name) && (row.item_name || row._fetched_item_name) !== row.item_code
							? `<span style="color:#64748b;font-size:10px;white-space:nowrap;">${esc(row.item_name || row._fetched_item_name)}</span>`
							: ''}
						${so_short
							? `<span style="background:#ede9fe;color:#4c1d95;border-radius:6px;
									padding:1px 6px;font-size:9px;font-weight:700;white-space:nowrap;flex-shrink:0;">SO·${esc(so_short)}</span>`
							: ''}
						${mfg
							? `<span style="background:${mfg_bg};color:${mfg_clr};border-radius:6px;
									padding:1px 6px;font-size:9px;font-weight:700;white-space:nowrap;flex-shrink:0;">${esc(mfg)}</span>`
							: ''}
						<span style="background:#eef2ff;color:#6366f1;border-radius:6px;
							padding:1px 6px;font-size:9px;font-weight:600;white-space:nowrap;flex-shrink:0;
							letter-spacing:0.2px;">${mfg_d}M·${grn_d}G·${pm_d}P</span>
					</div>
				</td>

				<!-- QTY -->
				<td style="padding:6px 10px;text-align:right;border-bottom:1px solid #ede9fe;
					white-space:nowrap;width:72px;">
					<span style="font-weight:700;color:#1e1b4b;font-size:11px;">${row.planned_qty || 0}</span>
					<span style="color:#a5b4fc;font-size:9px;margin-left:2px;">${esc(row.stock_uom || '')}</span>
				</td>

				<!-- PLANNED START -->
				<td style="padding:5px 8px;border-bottom:1px solid #ede9fe;">
					<div style="display:flex;gap:3px;align-items:center;">
						<input type="date" class="md-fg-sdate" data-row-name="${esc(row.name)}"
							value="${start_date}" data-original="${start_date}" style="${date_inp}"/>
						<input type="text" class="md-fg-stime" data-row-name="${esc(row.name)}"
							value="${start_time}" data-original="${start_time}"
							placeholder="HH:MM" maxlength="5" style="${time_inp}"/>
					</div>
				</td>

				<!-- arrow -->
				<td style="padding:6px 4px;border-bottom:1px solid #ede9fe;color:#c4b5fd;
					font-size:12px;text-align:center;width:16px;">→</td>

				<!-- PLANNED END -->
				<td style="padding:5px 8px;border-bottom:1px solid #ede9fe;">
					<div style="display:flex;gap:3px;align-items:center;">
						<input type="date" class="md-fg-edate" data-row-name="${esc(row.name)}"
							value="${end_date}" data-original="${end_date}" style="${date_inp}"/>
						<input type="text" class="md-fg-etime" data-row-name="${esc(row.name)}"
							value="${end_time}" data-original="${end_time}"
							placeholder="HH:MM" maxlength="5" style="${time_inp}"/>
					</div>
				</td>
			</tr>`;
		}).join('');

		return `
		<style>
			.md-fg-row:hover { background: #eef2ff !important; }
			.md-fg-row:hover input { border-color: #818cf8 !important; }
		</style>
		<div style="overflow:auto;border:1.5px solid #ddd6fe;border-radius:10px;
			box-shadow:0 2px 12px rgba(99,102,241,0.08);">
			<table style="width:100%;min-width:580px;border-collapse:collapse;">
				<thead>
					<tr style="background:linear-gradient(90deg,#1e1b4b 0%,#4338ca 100%);position:sticky;top:0;z-index:1;">
						<th style="padding:8px 8px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:center;width:28px;">#</th>
						<th style="padding:8px 12px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:left;">ITEM</th>
						<th style="padding:8px 10px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:right;width:72px;">QTY</th>
						<th style="padding:8px 8px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:left;" colspan="3">PLANNED START → END ✏</th>
					</tr>
				</thead>
				<tbody>${rows_html}</tbody>
			</table>
		</div>`;
	}

	// ── Step 2: Sub Assembly table (collapsible tree) ──────────────────────

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

		// ── Build ordered groups (deepest SFG first → top SFG last) ───────
		const _group_order = [];
		const _group_map   = {};  // production_item → { rows, item_name, chain_id }
		sfg_items.forEach(row => {
			const key = row.production_item || '(unknown)';
			if (!_group_map[key]) {
				_group_map[key] = { rows: [], item_name: row.item_name || '', chain_id: row.production_plan_item || '' };
				_group_order.push(key);
			}
			_group_map[key].rows.push(row);
		});
		_group_order.reverse();

		// ── Generate one collapsible card per SFG group ────────────────────
		const groups_html = _group_order.map((item_code, g_idx) => {
			const grp      = _group_map[item_code];
			const chain_id = grp.chain_id;
			const pal      = sfg_chain_color[chain_id] || SFG_PALETTE[g_idx % SFG_PALETTE.length];
			const clabel   = sfg_chain_label[chain_id] || chain_id.slice(-4);
			const grp_id   = `md-sfg-grp-${g_idx}`;
			const batch_n  = grp.rows.length;

			// Summary stats
			const total_qty = grp.rows.reduce((s, r) => s + (r.qty || 0), 0);
			const uom_rep   = grp.rows[0]?.uom || grp.rows[0]?.stock_uom || '';
			const start_rep = grp.rows[0]?.schedule_date;
			const end_rep   = grp.rows[grp.rows.length - 1]?.custom_schedule_end_date;
			const start_d   = start_rep ? frappe.datetime.str_to_user(start_rep.slice(0, 10)) : '—';
			const end_d     = end_rep   ? frappe.datetime.str_to_user(end_rep.slice(0, 10))   : '—';
			// Representative MFG type (first row)
			const mfg_rep   = grp.rows[0]?.type_of_manufacturing || 'In House';
			const mfg_bg    = mfg_rep === 'In House' ? '#dbeafe' : mfg_rep === 'Subcontract' ? '#fef3c7' : '#dcfce7';
			const mfg_clr   = mfg_rep === 'In House' ? '#1e40af' : mfg_rep === 'Subcontract' ? '#92400e' : '#14532d';
			// Aggregate days (from first batch)
			const mfg_days  = grp.rows[0]?.custom_mfg_days || '';
			const grn_days  = grp.rows[0]?.custom_grn_days || '';
			const pm_days   = grp.rows[0]?.custom_pm_days  || '';

			// Pipeline position label
			const pos_label = g_idx === 0 ? 'Top · runs last'
				: g_idx === _group_order.length - 1 ? 'Deepest · runs first'
				: `Level ${g_idx + 1}`;
			const pos_bg    = g_idx === 0 ? '#dcfce7' : g_idx === _group_order.length - 1 ? '#fee2e2' : '#ede9fe';
			const pos_clr   = g_idx === 0 ? '#14532d' : g_idx === _group_order.length - 1 ? '#991b1b' : '#4c1d95';

			// ── Batch rows ─────────────────────────────────────────────────
			const batch_rows_html = grp.rows.map((row, b_idx) => {
				const mfg     = row.type_of_manufacturing || '';
				const sel_bg  = mfg === 'In House' ? '#dbeafe' : mfg === 'Subcontract' ? '#fef3c7' : '#dcfce7';
				const sel_clr = mfg === 'In House' ? '#1e40af' : mfg === 'Subcontract' ? '#92400e' : '#14532d';

				const start_date = to_date_part(row.schedule_date);
				const start_time = to_time_part(row.schedule_date);
				const end_date   = to_date_part(row.custom_schedule_end_date);
				const end_time   = to_time_part(row.custom_schedule_end_date);
				const row_bg     = b_idx % 2 === 0 ? '#fafafe' : '#ffffff';

				return `
				<tr class="md-sfg-batch-row" style="border-left:3px solid ${pal.dot};background:${row_bg};"
					data-sfg-name="${esc(row.name)}" data-chain="${esc(chain_id)}" data-group="${grp_id}">

					<!-- Batch label -->
					<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;white-space:nowrap;width:52px;">
						<div style="display:inline-flex;align-items:center;justify-content:center;
							width:30px;height:20px;border-radius:6px;
							background:${pal.bg};border:1px solid ${pal.border};">
							<span style="font-size:9px;font-weight:800;color:${pal.text};">B${b_idx}</span>
						</div>
					</td>

					<!-- MFG type (read-only badge) -->
					<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
						<span style="display:inline-block;padding:2px 8px;border-radius:12px;
							font-size:10px;font-weight:600;background:${sel_bg};color:${sel_clr};">
							${esc(mfg || '—')}
						</span>
						${mfg === 'Subcontract' && row.supplier
							? `<div style="margin-top:3px;font-size:10px;color:#92400e;background:#fffbeb;
									display:inline-block;padding:2px 6px;border-radius:6px;border:1px solid #fcd34d;">
									${esc(row.supplier)}
								</div>`
							: ''}
					</td>

					<!-- Mfg / GRN / PM days -->
					<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;text-align:center;width:60px;">
						${row.custom_mfg_days ? `<span style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_mfg_days)}</span>` : '<span style="color:#cbd5e1;">—</span>'}
					</td>
					<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;text-align:center;width:60px;">
						${row.custom_grn_days ? `<span style="color:#2563eb;font-size:11px;font-weight:600;">${esc(row.custom_grn_days)}</span>` : '<span style="color:#cbd5e1;">—</span>'}
					</td>
					<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;text-align:center;width:60px;">
						${row.custom_pm_days ? `<span style="color:#7c3aed;font-size:11px;font-weight:600;">${esc(row.custom_pm_days)}</span>` : '<span style="color:#cbd5e1;">—</span>'}
					</td>

					<!-- QTY -->
					<td style="padding:7px 10px;text-align:right;border-bottom:1px solid #f0f0ff;white-space:nowrap;width:72px;">
						<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${row.qty || 0}</span>
						<span style="color:#94a3b8;font-size:10px;margin-left:2px;">${esc(uom_rep)}</span>
					</td>

					<!-- SCHEDULE START -->
					<td style="padding:5px 10px;border-bottom:1px solid #f0f0ff;">
						<div style="display:flex;gap:4px;align-items:center;">
							<input type="date" class="md-sfg-sdate" data-sfg-name="${esc(row.name)}"
								value="${start_date}" data-original="${start_date}" style="${date_inp}"/>
							<input type="text" class="md-sfg-stime" data-sfg-name="${esc(row.name)}"
								value="${start_time}" data-original="${start_time}"
								placeholder="HH:MM" maxlength="5" style="${time_inp}"/>
						</div>
					</td>

					<!-- SCHEDULE END -->
					<td style="padding:5px 10px;border-bottom:1px solid #f0f0ff;">
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

			return `
			<!-- SFG Group ${g_idx}: ${esc(item_code)} -->
			<div class="md-sfg-group" data-group-id="${grp_id}"
				style="border:1.5px solid ${pal.border};border-radius:10px;overflow:hidden;
					margin-bottom:10px;box-shadow:0 1px 4px rgba(79,70,229,0.06);">

				<!-- Group header (click to toggle) -->
				<div class="md-sfg-group-header" data-target="${grp_id}"
					style="display:flex;align-items:center;justify-content:space-between;
						padding:10px 14px;cursor:pointer;user-select:none;
						background:linear-gradient(90deg,${pal.bg} 0%,#fff 100%);
						border-bottom:1.5px solid ${pal.border};transition:background 0.15s;">

					<div style="display:flex;align-items:center;gap:10px;min-width:0;">
						<div style="width:4px;height:36px;background:${pal.dot};border-radius:3px;flex-shrink:0;"></div>
						<div style="min-width:0;">
							<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
								<span style="font-size:13px;font-weight:700;color:#1e1b4b;">${esc(item_code)}</span>
								${grp.item_name && grp.item_name !== item_code
									? `<span style="font-size:10px;color:#94a3b8;">${esc(grp.item_name)}</span>`
									: ''}
								<div style="display:inline-flex;align-items:center;gap:4px;
									background:${pal.bg};border:1px solid ${pal.border};border-radius:20px;padding:2px 8px;">
									<div style="width:6px;height:6px;border-radius:50%;background:${pal.dot};flex-shrink:0;"></div>
									<span style="font-size:9px;font-weight:700;color:${pal.text};">Chain ${esc(clabel)}</span>
								</div>
								<span style="background:${pos_bg};color:${pos_clr};border-radius:10px;
									padding:2px 8px;font-size:9px;font-weight:700;">${pos_label}</span>
							</div>
							<div style="display:flex;align-items:center;gap:10px;margin-top:4px;flex-wrap:wrap;">
								<span style="font-size:10px;color:#64748b;">
									<span style="font-weight:700;color:${pal.dot};">${batch_n}</span>
									batch${batch_n !== 1 ? 'es' : ''}
								</span>
								<span style="font-size:10px;color:#94a3b8;">·</span>
								<span style="font-size:10px;color:#64748b;">
									<span style="font-weight:600;color:#374151;">${total_qty}</span> ${esc(uom_rep)}
								</span>
								<span style="font-size:10px;color:#94a3b8;">·</span>
								<span style="font-size:10px;color:#64748b;">${start_d} → ${end_d}</span>
								${mfg_days ? `<span style="font-size:10px;color:#2563eb;font-weight:600;">${esc(mfg_days)}M</span>` : ''}
								${grn_days ? `<span style="font-size:10px;color:#2563eb;font-weight:600;">${esc(grn_days)}G</span>` : ''}
								${pm_days  ? `<span style="font-size:10px;color:#7c3aed;font-weight:600;">${esc(pm_days)}P</span>` : ''}
								<span style="background:${mfg_bg};color:${mfg_clr};border-radius:10px;
									padding:2px 8px;font-size:9px;font-weight:700;">${esc(mfg_rep)}</span>
							</div>
						</div>
					</div>

					<div class="md-sfg-chevron" data-target="${grp_id}"
						style="width:24px;height:24px;border-radius:6px;flex-shrink:0;
							display:flex;align-items:center;justify-content:center;
							background:rgba(0,0,0,0.04);transition:transform 0.22s ease;">
						<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
							<path d="M2 4.5L6 8L10 4.5" stroke="${pal.dot}" stroke-width="1.8"
								stroke-linecap="round" stroke-linejoin="round"/>
						</svg>
					</div>
				</div>

				<!-- Batch rows table -->
				<div class="md-sfg-group-body" id="${grp_id}"
					style="overflow:hidden;transition:max-height 0.28s ease,opacity 0.22s ease;max-height:2000px;opacity:1;">
					<table style="width:100%;min-width:680px;border-collapse:collapse;">
						<thead>
							<tr style="background:#f8f7ff;border-bottom:1px solid ${pal.border};">
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;text-align:center;width:52px;">BATCH</th>
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;">MFG TYPE</th>
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;text-align:center;width:60px;">MFG</th>
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;text-align:center;width:60px;">GRN</th>
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;text-align:center;width:60px;">PM</th>
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;text-align:right;width:72px;">QTY</th>
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;">SCHEDULE START ✏</th>
								<th style="padding:7px 10px;color:${pal.text};font-size:9px;font-weight:700;
									letter-spacing:0.5px;">SCHEDULE END ✏</th>
							</tr>
						</thead>
						<tbody>${batch_rows_html}</tbody>
					</table>
				</div>
			</div>`;
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
				<div style="width:5px;height:24px;background:linear-gradient(180deg,#4338ca,#7c3aed);
					border-radius:3px;flex-shrink:0;"></div>
				<div>
					<div style="font-size:15px;font-weight:700;color:#1e1b4b;line-height:1.2;">Sub Assembly Items</div>
					<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Click a group to expand · edit schedule dates</div>
				</div>
			</div>
			<div style="display:flex;align-items:center;gap:8px;">
				<span style="background:#eef2ff;color:#4338ca;border-radius:8px;padding:3px 10px;
					font-size:11px;font-weight:700;border:1px solid #c7d2fe;">
					${_group_order.length} SFG group${_group_order.length !== 1 ? 's' : ''}
				</span>
				<span style="background:#f5f3ff;color:#6d28d9;border-radius:8px;padding:3px 10px;
					font-size:11px;font-weight:700;border:1px solid #ddd6fe;">
					${sfg_items.length} batch${sfg_items.length !== 1 ? 'es' : ''}
				</span>
			</div>
		</div>
		<div id="md-sfg-tree">${groups_html}</div>`;
	}

	// ── Step 3: MR Items table ─────────────────────────────────────────────

	function build_mr_table() {
		if (!mr_items.length) {
			return '<div style="padding:20px;text-align:center;color:#94a3b8;font-style:italic;">No material request items.</div>';
		}

		const date_inp = `border:1.5px solid #ddd6fe;border-radius:7px;padding:5px 8px;font-size:11px;
			color:#3730a3;background:#fafafe;outline:none;font-family:inherit;
			transition:border-color 0.15s,box-shadow 0.15s;width:112px;`;

		const rows_html = mr_items.map((row, i) => {
			const so_short  = (row.sales_order || '').replace(/\D/g, '').slice(-5);
			const start_val = row.custom_start_date ? row.custom_start_date.slice(0, 10) : '';
			const sched_val = row.schedule_date     ? row.schedule_date.slice(0, 10)     : '';
			const row_bg    = i % 2 === 0 ? '#ffffff' : '#faf5ff';

			const mr_suppliers = suppliers_by_item[row.item_code] || [];
			const mr_sup_opts  = mr_suppliers.map(s => {
				const sel = row.custom_supplier ? s.supplier === row.custom_supplier : !!s.is_default;
				return `<option value="${esc(s.supplier)}" data-lead="${s.lead_time_days || 0}"
					${sel ? 'selected' : ''}>${esc(s.supplier)}${s.is_default ? ' ★' : ''}</option>`;
			}).join('');

			return `
			<tr class="md-mr-row" style="background:${row_bg};" data-mr-name="${esc(row.name)}">

				<td style="padding:6px 8px;color:#a5b4fc;font-size:10px;font-weight:700;text-align:center;
					border-bottom:1px solid #ede9fe;width:28px;">${i + 1}</td>

				<td style="padding:6px 14px;border-bottom:1px solid #ede9fe;min-width:170px;">
					<div style="font-weight:700;color:#1e1b4b;font-size:12px;line-height:1.3;">${esc(row.item_code)}</div>
					${row.item_name && row.item_name !== row.item_code
						? `<div style="color:#94a3b8;font-size:10px;margin-top:1px;">${esc(row.item_name)}</div>`
						: ''}
					${so_short
						? `<span style="display:inline-block;margin-top:4px;background:#ede9fe;color:#4c1d95;
								border-radius:8px;padding:1px 7px;font-size:9px;font-weight:700;">SO·${esc(so_short)}</span>`
						: ''}
				</td>

				<td style="padding:6px 10px;text-align:right;border-bottom:1px solid #ede9fe;
					white-space:nowrap;width:72px;">
					<span style="font-weight:700;color:#1e1b4b;font-size:12px;">${row.quantity || 0}</span>
					<div style="color:#a5b4fc;font-size:9px;margin-top:1px;">${esc(row.uom || '')}</div>
				</td>

				<td style="padding:5px 10px;border-bottom:1px solid #ede9fe;min-width:160px;">
					${mr_suppliers.length
						? `<select class="md-mr-supplier" data-mr-name="${esc(row.name)}"
								style="width:100%;border:1.5px solid #fcd34d;border-radius:8px;padding:4px 8px;
									font-size:11px;color:#92400e;background:#fffbeb;outline:none;cursor:pointer;font-family:inherit;">
								<option value="">— Select Supplier —</option>
								${mr_sup_opts}
							</select>`
						: `<span style="color:#cbd5e1;font-size:11px;font-style:italic;">No suppliers</span>`
					}
				</td>

				<td style="padding:5px 10px;border-bottom:1px solid #ede9fe;">
					<div style="font-size:8px;color:#a5b4fc;font-weight:700;margin-bottom:3px;letter-spacing:0.5px;">ORDER DATE</div>
					<input type="date" class="md-mr-sdate" data-mr-name="${esc(row.name)}"
						value="${esc(start_val)}" data-original="${esc(start_val)}" style="${date_inp}"/>
				</td>

				<td style="padding:5px 10px;border-bottom:1px solid #ede9fe;">
					<div style="font-size:8px;color:#a5b4fc;font-weight:700;margin-bottom:3px;letter-spacing:0.5px;">RECEIVE BY</div>
					<input type="date" class="md-mr-edate" data-mr-name="${esc(row.name)}"
						value="${esc(sched_val)}" data-original="${esc(sched_val)}" style="${date_inp}"/>
				</td>
			</tr>`;
		}).join('');

		return `
		<style>
			.md-mr-row:hover { background: #f5f3ff !important; }
		</style>
		<div style="display:flex;align-items:center;justify-content:space-between;
			margin-bottom:14px;flex-wrap:wrap;gap:8px;">
			<div style="display:flex;align-items:center;gap:10px;">
				<div style="width:5px;height:24px;background:linear-gradient(180deg,#7c3aed,#4338ca);
					border-radius:3px;flex-shrink:0;"></div>
				<div>
					<div style="font-size:15px;font-weight:700;color:#1e1b4b;line-height:1.2;">Material Request Items</div>
					<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Edit supplier &amp; purchase dates per raw material</div>
				</div>
			</div>
			<span style="background:#eef2ff;color:#4338ca;border-radius:8px;padding:3px 10px;
				font-size:11px;font-weight:700;border:1px solid #c7d2fe;white-space:nowrap;">
				${mr_items.length} item${mr_items.length !== 1 ? 's' : ''}
			</span>
		</div>
		<div style="overflow-x:auto;border-radius:10px;border:1.5px solid #ddd6fe;
			box-shadow:0 2px 12px rgba(99,102,241,0.08);">
			<table style="width:100%;min-width:600px;border-collapse:collapse;">
				<thead>
					<tr style="background:linear-gradient(90deg,#1e1b4b 0%,#4338ca 100%);">
						<th style="padding:8px 8px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:center;width:28px;">#</th>
						<th style="padding:8px 14px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:left;">ITEM · SO</th>
						<th style="padding:8px 10px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:right;width:72px;">QTY</th>
						<th style="padding:8px 10px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:left;">SUPPLIER ✏</th>
						<th style="padding:8px 10px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:left;">ORDER DATE ✏</th>
						<th style="padding:8px 10px;color:#a5b4fc;font-size:9px;font-weight:700;
							letter-spacing:0.8px;text-align:left;">RECEIVE BY ✏</th>
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
		<div style="display:flex;align-items:flex-start;gap:8px;background:#fffbeb;border:1px solid #fde68a;
			border-radius:8px;padding:8px 12px;margin-bottom:10px;">
			<span style="font-size:14px;line-height:1.4;flex-shrink:0;">⚠</span>
			<span style="font-size:11px;color:#78350f;line-height:1.5;">
				This is a manual task — dates must be edited individually for each item and will not be updated automatically.
			</span>
		</div>
		<div class="md-layout" style="display:flex;border-radius:10px;overflow:hidden;
			box-shadow:0 2px 12px rgba(79,70,229,0.1);border:1px solid #e2e8f0;margin-bottom:4px;">

			<div id="md-stepper-wrap" style="flex-shrink:0;">
				${build_stepper_html(0)}
			</div>

			<div class="md-content" style="flex:1;padding:20px 18px 16px;min-width:0;">

				<!-- Step MR -->
				<div id="md-step-mr" class="md-step-pane">
					${has_mr ? build_mr_table() : ''}
				</div>

				<!-- Step SFG -->
				<div id="md-step-sfg" class="md-step-pane" style="display:none;">
					${has_sfg ? build_sfg_table() : ''}
				</div>

				<!-- Step FG -->
				<div id="md-step-fg" class="md-step-pane" style="display:none;">
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
	// Initialize to first step
	setTimeout(() => _go_to_step(0), 50);

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

	// ── Collapse/expand SFG groups ─────────────────────────────────────────

	d.$wrapper.on('click', '.md-sfg-group-header', function() {
		const target   = $(this).data('target');
		const $body    = d.$wrapper.find(`#${target}`);
		const $chevron = d.$wrapper.find(`.md-sfg-chevron[data-target="${target}"]`);
		if ($body.data('collapsed')) {
			$body.css({ 'max-height': '2000px', opacity: '1' }).data('collapsed', false);
			$chevron.css('transform', 'rotate(0deg)');
		} else {
			$body.css({ 'max-height': '0', opacity: '0' }).data('collapsed', true);
			$chevron.css('transform', 'rotate(-90deg)');
		}
	});

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
		// _fire_cascade(rn, 'start', dt, 'fg');
	});
	d.$wrapper.on('blur', '.md-fg-stime', function() {
		const rn = $(this).data('row-name');
		const dt = _read_dt(d.$wrapper.find(`.md-fg-sdate[data-row-name="${rn}"]`), $(this));
		// _fire_cascade(rn, 'start', dt, 'fg');
	});

	// FG — end date/time change
	d.$wrapper.on('change', '.md-fg-edate', function() {
		const rn = $(this).data('row-name');
		const dt = _read_dt($(this), d.$wrapper.find(`.md-fg-etime[data-row-name="${rn}"]`));
		// _fire_cascade(rn, 'end', dt, 'fg');
	});
	d.$wrapper.on('blur', '.md-fg-etime', function() {
		const rn = $(this).data('row-name');
		const dt = _read_dt(d.$wrapper.find(`.md-fg-edate[data-row-name="${rn}"]`), $(this));
		// _fire_cascade(rn, 'end', dt, 'fg');
	});

	// SFG — start date/time change
	d.$wrapper.on('change', '.md-sfg-sdate', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt($(this), d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${rn}"]`));
		// _fire_cascade(rn, 'start', dt, 'sfg');
	});
	d.$wrapper.on('blur', '.md-sfg-stime', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt(d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`), $(this));
		// _fire_cascade(rn, 'start', dt, 'sfg');
	});

	// SFG — end date/time change
	d.$wrapper.on('change', '.md-sfg-edate', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt($(this), d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${rn}"]`));
		// _fire_cascade(rn, 'end', dt, 'sfg');
	});
	d.$wrapper.on('blur', '.md-sfg-etime', function() {
		const rn = $(this).data('sfg-name');
		const dt = _read_dt(d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${rn}"]`), $(this));
		// _fire_cascade(rn, 'end', dt, 'sfg');
	});

	// MR — start date change only (end = start + lead_time + grn_days, server computes)
	d.$wrapper.on('change', '.md-mr-sdate', function() {
		const rn = $(this).data('mr-name');
		const dv = $(this).val();
		// if (dv) _fire_cascade(rn, 'start', `${dv} 10:00:00`, 'mr');
	});
}
