// Copyright (c) 2026, Ujwal Industries and contributors
// Manage Dates — Stepper dialog for Production Plan
// Loaded globally via app_include_js so it is available on the Production Plan form.

// ============================================================================
// Helpers
// ============================================================================

/** "HH:MM:SS" → total minutes (integer) or null */
function _time_to_minutes(t) {
	if (!t) return null;
	const parts = String(t).split(':');
	return parseInt(parts[0] || 0) * 60 + parseInt(parts[1] || 0);
}

/**
 * Called when the DATE picker fires `change`.
 * 1. Rejects dates strictly before today (unless allow_backdate) — resets to original.
 * 2. If the date falls on a holiday in constraints.holidays — advances to next working day.
 */
function _validate_date_change($date, $time, constraints) {
	const date_val = $date.val();   // "YYYY-MM-DD" or ""
	if (!date_val) return;

	// Use LOCAL date parts — toISOString() is UTC and will be wrong in IST after midnight
	const now        = new Date();
	const today_str  = now.getFullYear() + '-'
		+ String(now.getMonth() + 1).padStart(2, '0') + '-'
		+ String(now.getDate()).padStart(2, '0');

	// 1. Backdate guard
	if (!constraints.allow_backdate && date_val < today_str) {
		$date.val($date.data('original') || today_str);
		$time.val($time.data('original') || '');
		frappe.show_alert({ message: __('Backdated dates are not allowed. Reverted to original.'), indicator: 'orange' });
		return;
	}

	// 2. Holiday guard — advance day-by-day until a non-holiday working day is found
	if (constraints.holidays && constraints.holidays.size > 0) {
		let check = date_val;
		let tries  = 365;
		while (constraints.holidays.has(check) && tries-- > 0) {
			const d_obj = new Date(check + 'T00:00:00');
			d_obj.setDate(d_obj.getDate() + 1);
			check = d_obj.getFullYear() + '-'
				+ String(d_obj.getMonth() + 1).padStart(2, '0') + '-'
				+ String(d_obj.getDate()).padStart(2, '0');
		}
		if (check !== date_val) {
			$date.val(check);
			const p = check.split('-');
			frappe.show_alert({
				message: __('Selected date is a holiday. Reset to next working day: ') + p[2] + '-' + p[1] + '-' + p[0],
				indicator: 'orange',
			});
		}
	}
}

/**
 * Called on `blur` of the TIME text input (HH:MM 24h).
 * Enforces:
 *  1. Valid HH:MM 24h format — rejects garbage silently
 *  2. No past time when the selected date is today — resets to now + alert
 *  3. Time within shift hours — resets to shift start + alert
 *  4. Not in lunch break — resets to lunch end + alert
 */
function _validate_time_blur($date, $time, constraints) {
	const time_val = $time.val().trim();
	if (!time_val) return;

	// 1. Must be HH:MM with valid ranges
	if (!/^\d{2}:\d{2}$/.test(time_val)) { $time.val(''); return; }
	const [h, m]     = time_val.split(':').map(Number);
	if (h > 23 || m > 59)                { $time.val(''); return; }
	const total_mins = h * 60 + m;

	// 2. Backdate guard — only when date == today
	if (!constraints.allow_backdate) {
		const date_val  = $date.val();
		const _now      = new Date();
		const today_str = _now.getFullYear() + '-'
			+ String(_now.getMonth() + 1).padStart(2, '0') + '-'
			+ String(_now.getDate()).padStart(2, '0');
		if (date_val === today_str) {
			const now      = new Date();
			const now_mins = now.getHours() * 60 + now.getMinutes();
			if (total_mins < now_mins) {
				$time.val(String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0'));
				frappe.show_alert({ message: __('Past time not allowed. Reset to current time.'), indicator: 'orange' });
				return;
			}
		}
	}

	// 3 & 4. Shift-hour + lunch guard
	if (constraints.shift_wise && constraints.shift) {
		const s           = constraints.shift;
		const shift_start = _time_to_minutes(s.start_time);
		const shift_end   = _time_to_minutes(s.end_time);
		const lunch_start = _time_to_minutes(s.custom_lunch_start_time);
		const lunch_end   = _time_to_minutes(s.custom_lunch_end_time);

		if (shift_start !== null && shift_end !== null) {
			if (total_mins < shift_start || total_mins > shift_end) {
				$time.val(String(s.start_time).slice(0, 5));
				frappe.show_alert({
					message: __('Time must be within shift hours (') + s.start_time.slice(0, 5) + __(' – ') + s.end_time.slice(0, 5) + ').',
					indicator: 'orange',
				});
				return;
			}
		}
		if (lunch_start !== null && lunch_end !== null) {
			if (total_mins >= lunch_start && total_mins < lunch_end) {
				$time.val(String(s.custom_lunch_end_time).slice(0, 5));
				frappe.show_alert({
					message: __('Lunch break (') + s.custom_lunch_start_time.slice(0, 5) + ' – ' + s.custom_lunch_end_time.slice(0, 5) + __('). Reset to ') + s.custom_lunch_end_time.slice(0, 5) + '.',
					indicator: 'orange',
				});
				return;
			}
		}
	}
}

// ============================================================================
// Entry point — fires constraints + suppliers batch in parallel, then opens dialog
// ============================================================================

function open_parallel_manage_dates_dialog(frm) {
	if (!(frm.doc.po_items || []).length) {
		frappe.show_alert({ message: __('No FG items available.'), indicator: 'orange' });
		return;
	}

	// Latch: wait for both independent API calls before building the dialog
	let _ready       = 0;
	let _constraints = null;
	let _suppliers   = {};

	function _try_build() {
		if (++_ready === 2) _build_manage_dates_dialog(frm, _constraints, _suppliers);
	}

	// Call 1: shift/holiday constraints
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.pp_fg_dates.get_production_plan_constraints',
		callback(r) {
			const c    = r.message || {};
			_constraints = {
				shift_wise:     !!c.shift_wise,
				allow_backdate: !!c.allow_backdate,
				shift:          c.shift   || null,
				holidays:       new Set(c.holidays || []),
			};
			_try_build();
		},
	});

	// Call 2: subcontracting suppliers for FG + SFG + MR items (in parallel)
	const _all_item_codes = [
		...(frm.doc.po_items            || []).map(r => r.item_code),
		...(frm.doc.sub_assembly_items  || []).map(r => r.production_item),
		...(frm.doc.mr_items            || []).map(r => r.item_code),
	].filter(Boolean);
	frappe.call({
		method: 'ujwal_industries.ujwal_industries.overrides.pp_fg_dates.get_items_suppliers_batch',
		args: { item_codes: JSON.stringify([...new Set(_all_item_codes)]) },
		callback(r) {
			_suppliers = r.message || {};
			_try_build();
		},
	});
}

// ============================================================================
// Dialog builder
// ============================================================================

function _build_manage_dates_dialog(frm, constraints, suppliers_by_item) {
	suppliers_by_item = suppliers_by_item || {};

	const po_items  = frm.doc.po_items || [];
	const sfg_items = frm.doc.sub_assembly_items || [];
	const mr_items  = frm.doc.mr_items || [];

	const has_sfg = sfg_items.length > 0;
	const has_mr  = mr_items.length > 0;

	const ALL_STEPS = [
		{ id: 'fg',  label: 'FG Items',      icon: '1' },
		...(has_sfg ? [{ id: 'sfg', label: 'Sub Assembly', icon: '2' }] : []),
		...(has_mr  ? [{ id: 'mr',  label: 'MR Items',     icon: has_sfg ? '3' : '2' }] : []),
	];

	// ── Chain color palette (5 slots, cycled for >5 FG rows) ──────────────
	// Used to visually group sub_assembly_items by their parent FG row.
	const SFG_PALETTE = [
		{ dot: '#7c3aed', bg: '#f5f3ff', border: '#c4b5fd', text: '#4c1d95' },  // violet
		{ dot: '#059669', bg: '#f0fdf4', border: '#6ee7b7', text: '#065f46' },  // emerald
		{ dot: '#d97706', bg: '#fffbeb', border: '#fde68a', text: '#78350f' },  // amber
		{ dot: '#dc2626', bg: '#fff1f2', border: '#fecdd3', text: '#881337' },  // rose
		{ dot: '#0284c7', bg: '#f0f9ff', border: '#bae6fd', text: '#0c4a6e' },  // sky
	];

	// po_item.name → palette color entry + short chain label "A · 00014"
	const sfg_chain_color = {};
	const sfg_chain_label = {};
	po_items.forEach((po, i) => {
		sfg_chain_color[po.name] = SFG_PALETTE[i % SFG_PALETTE.length];
		const so_nums = (po.sales_order || '').replace(/\D/g, '').slice(-5);
		sfg_chain_label[po.name] = String.fromCharCode(65 + i) + (so_nums ? ' · ' + so_nums : '');
	});

	// ── Tiny format helpers ────────────────────────────────────────────────

	function to_date_part(val) {
		if (!val) return '';
		return String(val).slice(0, 10);
	}

	function to_time_part(val) {
		if (!val) return '';
		const s = String(val);
		return s.length > 10 ? s.slice(11, 16) : '';
	}

	/** Parse "YYYY-MM-DD HH:MM:SS" → Date (local time, avoids UTC interpretation bugs). */
	function _parse_local_dt(str) {
		if (!str) return null;
		const [date, time] = String(str).split(' ');
		const [y, mo, d] = (date || '').split('-').map(Number);
		const [h, mn] = (time || '10:00').split(':').map(Number);
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
			const mfg     = row.custom_manufacturing_type || '';
			const row_bg  = i % 2 === 0 ? '#ffffff' : '#f8f7ff';
			const sel_bg  = mfg === 'In House'    ? '#dbeafe'
				          : mfg === 'Subcontract' ? '#fef3c7' : '#f1f5f9';
			const sel_clr = mfg === 'In House'    ? '#1e40af'
				          : mfg === 'Subcontract' ? '#92400e' : '#64748b';

			const date_val = to_date_part(row.planned_start_date);
			const time_val = to_time_part(row.planned_start_date);

			// Supplier options — default supplier pre-selected (or row.custom_supplier if set)
			const item_suppliers  = suppliers_by_item[row.item_code] || [];
			const supplier_options = item_suppliers.map(s => {
				const selected = row.custom_supplier
					? s.supplier === row.custom_supplier
					: !!s.is_default;
				return `<option value="${esc(s.supplier)}" data-lead="${s.lead_time_days}"
					${selected ? 'selected' : ''}>${esc(s.supplier)}${s.is_default ? ' ★' : ''}</option>`;
			}).join('');

			return `
			<tr style="background:${row_bg};" data-row-name="${esc(row.name)}">
				<td style="padding:10px 12px;color:#94a3b8;font-size:11px;text-align:center;
					border-bottom:1px solid #f0f0ff;width:36px;">${i + 1}</td>

				<td style="padding:10px 14px;border-bottom:1px solid #f0f0ff;">
					<div style="font-weight:600;color:#1e1b4b;font-size:13px;">${esc(row.item_code)}</div>
					${row.item_name && row.item_name !== row.item_code
						? `<div style="color:#94a3b8;font-size:11px;margin-top:2px;">${esc(row.item_name)}</div>`
						: ''}
				</td>

				<td style="padding:10px 12px;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					${row.sales_order
						? `<span style="font-size:11px;font-weight:600;color:#2563eb;">${esc(row.sales_order)}</span>`
						: '<span style="color:#cbd5e1;font-style:italic;font-size:11px;">—</span>'}
				</td>

				<td style="padding:10px 12px;border-bottom:1px solid #f0f0ff;min-width:170px;">
					<select class="md-mfg-select" data-row-name="${esc(row.name)}"
						style="border:none;border-radius:20px;padding:4px 12px;font-size:11px;font-weight:600;
							background:${sel_bg};color:${sel_clr};cursor:pointer;outline:none;appearance:auto;width:100%;">
						<option value="" ${!mfg ? 'selected' : ''} disabled>— Manufacturing Type —</option>
						<option value="In House"    ${mfg === 'In House'    ? 'selected' : ''}>In House</option>
						<option value="Subcontract" ${mfg === 'Subcontract' ? 'selected' : ''}>Subcontract</option>
					</select>

					<!-- Supplier dropdown — visible only for Subcontract rows -->
					<div class="md-supplier-wrap" data-row-name="${esc(row.name)}"
						style="margin-top:7px;display:${mfg === 'Subcontract' ? 'block' : 'none'};">
						<select class="md-supplier-select" data-row-name="${esc(row.name)}"
							style="width:100%;border:1.5px solid #fcd34d;border-radius:8px;padding:4px 8px;
								font-size:11px;color:#92400e;background:#fffbeb;outline:none;cursor:pointer;font-family:inherit;">
							<option value="">— Select Supplier —</option>
							${supplier_options}
						</select>
						<div class="md-lead-info" data-row-name="${esc(row.name)}"
							style="font-size:10px;color:#a16207;margin-top:3px;min-height:14px;padding-left:2px;"></div>
					</div>
				</td>

				<td style="padding:10px 14px;text-align:right;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					<span style="font-weight:600;color:#1e1b4b;font-size:13px;">${row.planned_qty || 0}</span>
					<span style="color:#94a3b8;font-size:11px;margin-left:4px;">${esc(row.stock_uom)}</span>
				</td>

				<td style="padding:8px 12px;border-bottom:1px solid #f0f0ff;">
					<div style="display:flex;gap:6px;align-items:center;">
						<input type="date" class="md-start-date" data-row-name="${esc(row.name)}"
							value="${date_val}" data-original="${date_val}"
							style="${input_style}width:130px;"/>
						<input type="text" class="md-start-time" data-row-name="${esc(row.name)}"
							value="${time_val}" data-original="${time_val}"
							placeholder="HH:MM" maxlength="5"
							style="${input_style}width:70px;text-align:center;letter-spacing:1px;
								font-variant-numeric:tabular-nums;font-weight:600;"/>
					</div>
				</td>

				<td style="padding:10px 12px;border-bottom:1px solid #f0f0ff;">
					<div class="md-end-display" data-row-name="${esc(row.name)}"
						data-raw-end="${esc(row.custom_planned_end_date || '')}" 
						style="background:#f1f5f9;color:#64748b;font-size:12px;padding:6px 11px;
							border-radius:8px;display:inline-block;min-width:155px;line-height:1.4; margin-top: 16px;">
						${display_dt(row.custom_planned_end_date)}
					</div>
					<!-- Breakdown: "Lead: Xd · GRN: Yd" or "Prod: Xh" — filled by _refresh_end_date -->
					<div class="md-end-breakdown" data-row-name="${esc(row.name)}"
						style="font-size:10px;color:#94a3b8;margin-top:4px;min-height:14px;padding-left:2px;"></div>
				</td>
			</tr>`;
		}).join('');

		return `
		<div class="md-table-wrap" style="border:1px solid #e2e8f0;border-radius:10px;overflow:auto;
			box-shadow:0 2px 8px rgba(79,70,229,0.07);-webkit-overflow-scrolling:touch;">
			<table style="width:100%;min-width:700px;border-collapse:collapse;">
				<thead>
					<tr style="background:linear-gradient(90deg,#1e1b4b 0%,#3730a3 100%);">
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:center;">#</th>
						<th style="padding:10px 14px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">ITEM</th>
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">SALES ORDER</th>
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">MFG TYPE / SUPPLIER</th>
						<th style="padding:10px 14px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:right;">QTY</th>
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">PLANNED START ✏</th>
						<th style="padding:10px 12px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">PLANNED END</th>
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
			const sel_bg  = mfg === 'In House'          ? '#dbeafe'
				          : mfg === 'Subcontract'       ? '#fef3c7'
				          : '#dcfce7';
			const sel_clr = mfg === 'In House'          ? '#1e40af'
				          : mfg === 'Subcontract'       ? '#92400e'
				          : '#14532d';

			const indent      = row.indent || 0;
			const item_left   = indent * 16;
			// Tree branch character for indented rows
			const tree_chr    = indent > 0 ? `<span style="color:${pal.border};margin-right:3px;">└─</span>` : '';

			const start_date = to_date_part(row.schedule_date);
			const start_time = to_time_part(row.schedule_date);
			const end_date   = to_date_part(row.custom_schedule_end_date);
			const end_time   = to_time_part(row.custom_schedule_end_date);

			// Supplier dropdown options for this SFG item
			const sfg_suppliers = suppliers_by_item[row.production_item] || [];
			const sfg_sup_opts  = sfg_suppliers.map(s => {
				const sel = row.supplier ? s.supplier === row.supplier : !!s.is_default;
				return `<option value="${esc(s.supplier)}" data-lead="${s.lead_time_days}"
					${sel ? 'selected' : ''}>${esc(s.supplier)}${s.is_default ? ' ★' : ''}</option>`;
			}).join('');

			return `
			<tr style="border-left:3px solid ${pal.dot};background:${i % 2 === 0 ? '#fff' : '#fafafe'};"
				data-sfg-name="${esc(row.name)}" data-chain="${esc(chain_id)}">

				<td style="padding:8px 10px;color:#94a3b8;font-size:11px;text-align:center;
					border-bottom:1px solid #f0f0ff;width:32px;">${i + 1}</td>

				<!-- Chain badge -->
				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					<div style="display:inline-flex;align-items:center;gap:4px;
						background:${pal.bg};border:1px solid ${pal.border};border-radius:20px;padding:3px 9px;">
						<div style="width:7px;height:7px;border-radius:50%;background:${pal.dot};flex-shrink:0;"></div>
						<span style="font-size:9px;font-weight:700;color:${pal.text};letter-spacing:0.2px;">${esc(clabel)}</span>
					</div>
				</td>

				<!-- Item + BOM tree indent -->
				<td style="padding:8px 14px;border-bottom:1px solid #f0f0ff;min-width:175px;">
					<div style="padding-left:${item_left}px;">
						${tree_chr}<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${esc(row.production_item)}</span>
					</div>
					${row.item_name && row.item_name !== row.production_item
						? `<div style="color:#94a3b8;font-size:10px;margin-top:1px;
								padding-left:${item_left + (indent > 0 ? 18 : 0)}px;">${esc(row.item_name)}</div>`
						: ''}
				</td>

				<!-- MFG TYPE + Supplier (Subcontract only) -->
				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;min-width:160px;">
					<select class="md-sfg-mfg" data-sfg-name="${esc(row.name)}"
						style="border:none;border-radius:20px;padding:3px 10px;font-size:11px;font-weight:600;
							background:${sel_bg};color:${sel_clr};cursor:pointer;outline:none;appearance:auto;width:100%;">
						<option value="In House"          ${mfg === 'In House'          ? 'selected' : ''}>In House</option>
						<option value="Subcontract"       ${mfg === 'Subcontract'       ? 'selected' : ''}>Subcontract</option>
					</select>
					<div class="md-sfg-supplier-wrap" data-sfg-name="${esc(row.name)}"
						style="margin-top:6px;display:${mfg === 'Subcontract' ? 'block' : 'none'};">
						<select class="md-sfg-supplier" data-sfg-name="${esc(row.name)}"
							style="width:100%;border:1.5px solid #fcd34d;border-radius:8px;padding:4px 8px;
								font-size:11px;color:#92400e;background:#fffbeb;outline:none;cursor:pointer;font-family:inherit;">
							<option value="">— Select Supplier —</option>
							${sfg_sup_opts}
						</select>
					</div>
				</td>

				<!-- QTY (readonly) -->
				<td style="padding:8px 10px;text-align:right;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${row.qty || 0}</span>
					<span style="color:#94a3b8;font-size:10px;margin-left:3px;">${esc(row.uom || row.stock_uom || '')}</span>
				</td>

				<!-- SCHEDULE START (schedule_date — editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<div style="display:flex;gap:4px;align-items:center;">
						<input type="date" class="md-sfg-sdate" data-sfg-name="${esc(row.name)}"
							value="${start_date}" data-original="${start_date}"
							style="${date_inp}"/>
						<input type="text" class="md-sfg-stime" data-sfg-name="${esc(row.name)}"
							value="${start_time}" data-original="${start_time}"
							placeholder="HH:MM" maxlength="5" style="${time_inp}"/>
					</div>
				</td>

				<!-- SCHEDULE END (custom_schedule_end_date — editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<div style="display:flex;gap:4px;align-items:center;">
						<input type="date" class="md-sfg-edate" data-sfg-name="${esc(row.name)}"
							value="${end_date}" data-original="${end_date}"
							style="${date_inp}"/>
						<input type="text" class="md-sfg-etime" data-sfg-name="${esc(row.name)}"
							value="${end_time}" data-original="${end_time}"
							placeholder="HH:MM" maxlength="5" style="${time_inp}"/>
					</div>
				</td>
			</tr>`;
		}).join('');

		// Chain legend badges shown in the step header
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
					<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Edit manufacturing type &amp; schedule dates per chain</div>
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
			<table style="width:100%;min-width:820px;border-collapse:collapse;">
				<thead>
					<tr style="background:linear-gradient(90deg,#1e1b4b 0%,#3730a3 100%);">
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:center;">#</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">CHAIN</th>
						<th style="padding:9px 14px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">ITEM</th>
						<th style="padding:9px 10px;color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:0.6px;text-align:left;">MFG TYPE ✏</th>
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
		const text_inp = `border:1.5px solid #c7d2fe;border-radius:7px;padding:5px 7px;font-size:11px;
			color:#3730a3;background:#fafafe;outline:none;font-family:inherit;width:100%;`;

		const rows_html = mr_items.map((row, i) => {
			const so_short = (row.sales_order || '').replace(/\D/g,'').slice(-5);
			const so_badge = so_short
				? `<span style="background:#ede9fe;color:#4c1d95;border-radius:10px;padding:2px 8px;
						font-size:9px;font-weight:700;">SO·${esc(so_short)}</span>`
				: '';

			const start_val = row.custom_start_date ? row.custom_start_date.slice(0,10) : '';
			const sched_val = row.schedule_date     ? row.schedule_date.slice(0,10)     : '';

			// Supplier dropdown — same pattern as FG / SFG items
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

				<!-- Sales Order badge -->
				<td style="padding:7px 10px;border-bottom:1px solid #f0f0ff;white-space:nowrap;">
					${so_badge}
				</td>

				<!-- Item Code + Name (readonly) -->
				<td style="padding:8px 14px;border-bottom:1px solid #f0f0ff;min-width:160px;">
					<span style="font-weight:600;color:#1e1b4b;font-size:12px;">${esc(row.item_code)}</span>
					${row.item_name && row.item_name !== row.item_code
						? `<div style="color:#94a3b8;font-size:10px;margin-top:1px;">${esc(row.item_name)}</div>`
						: ''}
				</td>

				<!-- Quantity + UOM (readonly) -->
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

				<!-- Start Date / custom_start_date (editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<input type="date" class="md-mr-sdate" data-mr-name="${esc(row.name)}"
						value="${esc(start_val)}" data-original="${esc(start_val)}"
						style="${date_inp}" />
				</td>

				<!-- Schedule Date (editable) -->
				<td style="padding:6px 10px;border-bottom:1px solid #f0f0ff;">
					<input type="date" class="md-mr-edate" data-mr-name="${esc(row.name)}"
						value="${esc(sched_val)}" data-original="${esc(sched_val)}"
						style="${date_inp}" />
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
			.md-start-date, .md-sfg-sdate, .md-sfg-edate { width: 100px !important; }
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
								<div style="font-size:11px;color:#94a3b8;margin-top:2px;">Edit manufacturing type &amp; planned start date</div>
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
		title: '📅  Reschedule Parallel Production Dates Chain',
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

	// Hide Back button on first step (dialog renders secondary button immediately)
	d.$wrapper.find('.btn-modal-secondary').hide();

	// ── SFG ripple flash tracking ──────────────────────────────────────────
	// Rows that need a highlight when Step 2 becomes visible.
	// Populated by _refresh_sfg_dates_for_chain, drained by _go_to_step.
	const _pending_sfg_flashes = new Set();

	/**
	 * Flash a single SFG row (and its date inputs) with a ~3s fade-out highlight.
	 * Uses JS transitions on inline background to avoid specificity conflicts.
	 */
	function _flash_sfg_row(sfg_rn) {
		const $row = d.$wrapper.find(`tr[data-sfg-name="${sfg_rn}"]`);
		if (!$row.length) return;

		// ── Row background — amber flash → original ──────────────────────
		const orig_bg = $row.css('background-color');
		$row.css({ background: 'rgba(251,191,36,0.28)', transition: 'none' });
		setTimeout(() => {
			$row.css({ background: orig_bg, transition: 'background 2.6s ease-out' });
		}, 80);
		setTimeout(() => { $row.css('transition', ''); }, 2800);

		// ── Date/time inputs — violet flash via CSS animation class ──────
		const sel = `.md-sfg-sdate[data-sfg-name="${sfg_rn}"],` +
		            `.md-sfg-stime[data-sfg-name="${sfg_rn}"],` +
		            `.md-sfg-edate[data-sfg-name="${sfg_rn}"],` +
		            `.md-sfg-etime[data-sfg-name="${sfg_rn}"]`;
		const $inputs = d.$wrapper.find(sel);
		$inputs.removeClass('sfg-input-flashing');
		// Force reflow so animation restarts if already applied
		void $inputs[0]?.offsetWidth;
		$inputs.addClass('sfg-input-flashing');
		setTimeout(() => $inputs.removeClass('sfg-input-flashing'), 3000);
	}

	// ── FG row flash tracking (queued when user is on Step 2) ─────────────
	const _pending_fg_flashes = new Set();

	// ── MR row flash tracking (queued when user is not on Step 3) ─────────
	const _pending_mr_flashes = new Set();

	/**
	 * Flash a single FG row (and its start date inputs) with a ~3s amber fade-out.
	 */
	function _flash_fg_row(po_name) {
		const $row = d.$wrapper.find(`tr[data-row-name="${po_name}"]`);
		if (!$row.length) return;

		const orig_bg = $row.css('background-color');
		$row.css({ background: 'rgba(251,191,36,0.28)', transition: 'none' });
		setTimeout(() => {
			$row.css({ background: orig_bg, transition: 'background 2.6s ease-out' });
		}, 80);
		setTimeout(() => { $row.css('transition', ''); }, 2800);

		const sel = `.md-start-date[data-row-name="${po_name}"],.md-start-time[data-row-name="${po_name}"]`;
		const $inputs = d.$wrapper.find(sel);
		$inputs.removeClass('sfg-input-flashing');
		void $inputs[0]?.offsetWidth;
		$inputs.addClass('sfg-input-flashing');
		setTimeout(() => $inputs.removeClass('sfg-input-flashing'), 3000);
	}

	/**
	 * Pulse the stepper circle for the given step index (0 = FG, 1 = SFG, etc.).
	 * Works regardless of which step is currently active.
	 */
	function _flash_step_indicator(step_idx) {
		const $circle = d.$wrapper.find(`.md-step-circle[data-step-idx="${step_idx}"]`);
		if (!$circle.length) return;
		$circle.css({ background: '#f59e0b', 'box-shadow': '0 0 0 6px rgba(245,158,11,0.4)', transition: 'none' });
		setTimeout(() => {
			$circle.css({ background: '', 'box-shadow': '', transition: 'background 1.4s ease, box-shadow 1.4s ease' });
			setTimeout(() => $circle.css('transition', ''), 1600);
		}, 650);
	}

	// ── MR row flash ───────────────────────────────────────────────────────

	/**
	 * Flash a single MR row (and its date inputs) with a ~3s amber fade-out.
	 */
	function _flash_mr_row(mr_rn) {
		const $row = d.$wrapper.find(`tr[data-mr-name="${mr_rn}"]`);
		if (!$row.length) return;

		const orig_bg = $row.css('background-color');
		$row.css({ background: 'rgba(251,191,36,0.28)', transition: 'none' });
		setTimeout(() => {
			$row.css({ background: orig_bg, transition: 'background 2.6s ease-out' });
		}, 80);
		setTimeout(() => { $row.css('transition', ''); }, 2800);

		const sel = `.md-mr-sdate[data-mr-name="${mr_rn}"],.md-mr-edate[data-mr-name="${mr_rn}"]`;
		const $inputs = d.$wrapper.find(sel);
		$inputs.removeClass('sfg-input-flashing');
		void $inputs[0]?.offsetWidth;
		$inputs.addClass('sfg-input-flashing');
		setTimeout(() => $inputs.removeClass('sfg-input-flashing'), 3000);
	}

	// ── Dialog state collectors ────────────────────────────────────────────

	/** Returns [{name, schedule_date, custom_schedule_end_date}, ...] from SFG inputs. */
	function _get_sfg_dates_from_dialog() {
		return sfg_items.map(row => {
			const sdate = d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${row.name}"]`).val();
			const stime = d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${row.name}"]`).val().trim();
			const edate = d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${row.name}"]`).val();
			const etime = d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${row.name}"]`).val().trim();
			return {
				name:                    row.name,
				schedule_date:            sdate ? `${sdate} ${/^\d{2}:\d{2}$/.test(stime) ? stime : '10:00'}:00` : '',
				custom_schedule_end_date: edate ? `${edate} ${/^\d{2}:\d{2}$/.test(etime) ? etime : '10:00'}:00` : '',
			};
		}).filter(r => r.schedule_date);
	}

	/** Returns [{name, planned_start_date, custom_planned_end_date}, ...] from FG inputs. */
	function _get_fg_dates_from_dialog() {
		return po_items.map(row => {
			const date_val = d.$wrapper.find(`.md-start-date[data-row-name="${row.name}"]`).val();
			const time_val = d.$wrapper.find(`.md-start-time[data-row-name="${row.name}"]`).val().trim();
			const $end     = d.$wrapper.find(`.md-end-display[data-row-name="${row.name}"]`);
			const end_val  = $end.data('raw-end') || $end.attr('data-raw-end') || '';
			return {
				name:                    row.name,
				planned_start_date:      date_val ? `${date_val} ${/^\d{2}:\d{2}$/.test(time_val) ? time_val : '10:00'}:00` : '',
				custom_planned_end_date: end_val,
			};
		}).filter(r => r.planned_start_date);
	}

	// ── MR ↔ SFG/FG cascade functions ─────────────────────────────────────

	/**
	 * After SFG dates change (FG cascade or SFG upward cascade), recalculate
	 * all MR item custom_start_date and schedule_date from the current dialog
	 * SFG schedule_dates. Updates Step 3 inputs without touching the DB.
	 */
	function _refresh_mr_from_sfg(po_item_name = null) {
		if (!has_mr) return;
		const sfg_dates_data = _get_sfg_dates_from_dialog();
		if (!sfg_dates_data.length) return;

		// Dim MR date inputs while recalculating
		d.$wrapper.find('.md-mr-sdate, .md-mr-edate').css('opacity', '0.45');

		const api_args = {
			production_plan_name: frm.doc.name,
			sfg_dates_data:       JSON.stringify(sfg_dates_data),
		};
		if (po_item_name) api_args.po_item_name = po_item_name;

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_mr_dates.recalculate_mr_dates_from_sfg',
			args: api_args,
			callback(r) {
				d.$wrapper.find('.md-mr-sdate, .md-mr-edate').css('opacity', '1');
				const results = r.message || {};
				let updated = 0;
				Object.entries(results).forEach(([mr_rn, dates]) => {
					if (dates.custom_start_date) {
						d.$wrapper.find(`.md-mr-sdate[data-mr-name="${mr_rn}"]`)
							.val(to_date_part(dates.custom_start_date))
							.data('original', to_date_part(dates.custom_start_date));
					}
					if (dates.schedule_date) {
						d.$wrapper.find(`.md-mr-edate[data-mr-name="${mr_rn}"]`)
							.val(to_date_part(dates.schedule_date))
							.data('original', to_date_part(dates.schedule_date));
					}
					if (ALL_STEPS[_step] && ALL_STEPS[_step].id === 'mr') {
						_flash_mr_row(mr_rn);
					} else {
						_pending_mr_flashes.add(mr_rn);
					}
					updated++;
				});
				if (updated > 0) {
					_flash_step_indicator(ALL_STEPS.findIndex(s => s.id === 'mr'));
				}
			},
		});
	}

	/**
	 * When an MR schedule_date changes, cascade upward to SFG then FG.
	 * Passes current dialog SFG/FG state as override baseline to the server.
	 */
	function _propagate_mr_upward(changed_mr_rn = null) {
		if (!has_sfg) return;

		// Collect MR schedule_dates {item_code: schedule_date}.
		// When a specific row changed, use ONLY that row so sibling rows
		// (same item_code, different SO chain) don't overwrite the new value.
		const mr_schedule_dates = {};
		if (changed_mr_rn) {
			const _cr = mr_items.find(r => r.name === changed_mr_rn);
			if (_cr) {
				const sched = d.$wrapper.find(`.md-mr-edate[data-mr-name="${changed_mr_rn}"]`).val();
				if (sched) mr_schedule_dates[_cr.item_code] = sched;
			}
		} else {
			mr_items.forEach(row => {
				const sched = d.$wrapper.find(`.md-mr-edate[data-mr-name="${row.name}"]`).val();
				if (sched) {
					const ex = mr_schedule_dates[row.item_code];
					if (!ex || sched > ex) mr_schedule_dates[row.item_code] = sched;
				}
			});
		}
		if (!Object.keys(mr_schedule_dates).length) return;

		const sfg_dates_override = _get_sfg_dates_from_dialog();
		const fg_dates_override  = _get_fg_dates_from_dialog();

		d.$wrapper.find('.md-sfg-sdate, .md-sfg-stime, .md-sfg-edate, .md-sfg-etime').css('opacity', '0.45');
		d.$wrapper.find('.md-start-date, .md-start-time').css('opacity', '0.45');

		const _pargs = {
			production_plan_name: frm.doc.name,
			mr_schedule_dates:    JSON.stringify(mr_schedule_dates),
			sfg_dates_override:   JSON.stringify(sfg_dates_override),
			fg_dates_override:    JSON.stringify(fg_dates_override),
		};
		if (changed_mr_rn) _pargs.mr_row_name_filter = changed_mr_rn;

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_mr_dates.propagate_mr_schedule_to_sfg_fg',
			args: _pargs,
			callback(r) {
				d.$wrapper.find('.md-sfg-sdate, .md-sfg-stime, .md-sfg-edate, .md-sfg-etime').css('opacity', '1');
				d.$wrapper.find('.md-start-date, .md-start-time').css('opacity', '1');

				const res         = r.message || {};
				const sfg_updates = res.sfg_updates || {};
				const fg_updates  = res.fg_updates  || {};
				const sfg_count   = Object.keys(sfg_updates).length;
				const fg_count    = Object.keys(fg_updates).length;

				// Update SFG rows
				Object.entries(sfg_updates).forEach(([rn, dates]) => {
					d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`).val(to_date_part(dates.schedule_date));
					d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${rn}"]`).val(to_time_part(dates.schedule_date));
					d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${rn}"]`).val(to_date_part(dates.custom_schedule_end_date));
					d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${rn}"]`).val(to_time_part(dates.custom_schedule_end_date));
					if (ALL_STEPS[_step] && ALL_STEPS[_step].id === 'sfg') {
						_flash_sfg_row(rn);
					} else {
						_pending_sfg_flashes.add(rn);
					}
				});
				if (sfg_count > 0) _flash_step_indicator(ALL_STEPS.findIndex(s => s.id === 'sfg'));

				// Update FG rows
				Object.entries(fg_updates).forEach(([po_name, dates]) => {
					d.$wrapper.find(`.md-start-date[data-row-name="${po_name}"]`).val(to_date_part(dates.planned_start_date));
					d.$wrapper.find(`.md-start-time[data-row-name="${po_name}"]`).val(to_time_part(dates.planned_start_date));
					const $end = d.$wrapper.find(`.md-end-display[data-row-name="${po_name}"]`);
					try {
						$end.html(frappe.datetime.str_to_user(dates.custom_planned_end_date));
					} catch(e) {
						$end.html(dates.custom_planned_end_date);
					}
					$end.data('raw-end', dates.custom_planned_end_date);
					$end.attr('data-raw-end', dates.custom_planned_end_date);
					if (ALL_STEPS[_step] && ALL_STEPS[_step].id === 'fg') {
						_flash_fg_row(po_name);
					} else {
						_pending_fg_flashes.add(po_name);
						_flash_step_indicator(ALL_STEPS.findIndex(s => s.id === 'fg'));
					}
				});

				if (sfg_count > 0 || fg_count > 0) {
					frappe.show_alert({
						message: __(`MR schedule change cascaded — ${sfg_count} SFG and ${fg_count} FG row(s) updated.`),
						indicator: 'blue',
					});
				}
			},
		});
	}

	function _go_to_step(idx) {
		_step = Math.max(0, Math.min(idx, ALL_STEPS.length - 1));

		// Refresh stepper sidebar
		d.$wrapper.find('#md-stepper-wrap').html(build_stepper_html(_step));

		// Replay any pending SFG flashes when entering the SFG pane
		if (ALL_STEPS[_step].id === 'sfg' && _pending_sfg_flashes.size > 0) {
			setTimeout(() => {
				_pending_sfg_flashes.forEach(rn => _flash_sfg_row(rn));
				_pending_sfg_flashes.clear();
			}, 60);
		}

		// Replay any pending FG flashes when going back to FG pane
		if (ALL_STEPS[_step].id === 'fg' && _pending_fg_flashes.size > 0) {
			setTimeout(() => {
				_pending_fg_flashes.forEach(pn => _flash_fg_row(pn));
				_pending_fg_flashes.clear();
			}, 60);
		}

		// Replay any pending MR flashes when entering the MR pane
		if (ALL_STEPS[_step].id === 'mr' && _pending_mr_flashes.size > 0) {
			setTimeout(() => {
				_pending_mr_flashes.forEach(rn => _flash_mr_row(rn));
				_pending_mr_flashes.clear();
			}, 60);
		}

		// Show correct step pane
		d.$wrapper.find('.md-step-pane').hide();
		d.$wrapper.find(`#md-step-${ALL_STEPS[_step].id}`).show();

		// Primary button label
		const is_last = (_step === ALL_STEPS.length - 1);
		d.set_primary_action(is_last ? __('Apply') : __('Next  →'), is_last ? _apply_changes : () => _go_next());

		// Back button visibility
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

	function _apply_changes() {
		// ── Collect current dialog values ──────────────────────────────────
		const po_data = po_items.map(row => {
			const rn       = row.name;
			const mfg_val  = d.$wrapper.find(`.md-mfg-select[data-row-name="${rn}"]`).val();
			const sup_val  = d.$wrapper.find(`.md-supplier-select[data-row-name="${rn}"]`).val();
			const date_val = d.$wrapper.find(`.md-start-date[data-row-name="${rn}"]`).val();
			const time_val = d.$wrapper.find(`.md-start-time[data-row-name="${rn}"]`).val().trim();
			const $end     = d.$wrapper.find(`.md-end-display[data-row-name="${rn}"]`);
			const end_val  = $end.data('raw-end') || $end.attr('data-raw-end') || '';
			const entry    = { name: rn };
			if (mfg_val)  entry.custom_manufacturing_type = mfg_val;
			if (sup_val)  entry.custom_supplier           = sup_val;
			if (date_val) entry.planned_start_date        = `${date_val} ${/^\d{2}:\d{2}$/.test(time_val) ? time_val : '10:00'}:00`;
			if (end_val)  entry.custom_planned_end_date   = end_val;
			return entry;
		});

		const sfg_data = sfg_items.map(row => {
			const rn        = row.name;
			const mfg_val   = d.$wrapper.find(`.md-sfg-mfg[data-sfg-name="${rn}"]`).val();
			const sup_val   = d.$wrapper.find(`.md-sfg-supplier[data-sfg-name="${rn}"]`).val();
			const sdate_val = d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`).val();
			const stime_val = d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${rn}"]`).val().trim();
			const edate_val = d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${rn}"]`).val();
			const etime_val = d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${rn}"]`).val().trim();
			const entry     = { name: rn };
			if (mfg_val)               entry.type_of_manufacturing    = mfg_val;
			if (sup_val !== undefined)  entry.supplier                = sup_val;
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

		// ── Direct DB save — bypasses all before_save / validate hooks ─────
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

	// ── Seed initial lead-time hints for Subcontract FG rows ──────────────

	po_items.forEach(row => {
		if ((row.custom_manufacturing_type || '') !== 'Subcontract') return;
		const $sup = d.$wrapper.find(`.md-supplier-select[data-row-name="${row.name}"]`);
		const lead = $sup.find(':selected').data('lead') || 0;
		if (lead) {
			d.$wrapper.find(`.md-lead-info[data-row-name="${row.name}"]`).text(`Lead time: ${lead}d`);
		}
	});

	// ── Recalculate FG end date via server API ─────────────────────────────

	/**
	 * Calls the server to forward-schedule custom_planned_end_date.
	 * Requires both date + valid HH:MM time to be set.
	 * Passes current supplier selection for Subcontract rows.
	 * Updates the breakdown sub-line ("Lead: Xd · GRN: Yd" / "Prod: Xh") from the response.
	 */
	function _refresh_end_date(row_name) {
		const row = po_items.find(r => r.name === row_name);
		if (!row) return;

		const $date    = d.$wrapper.find(`.md-start-date[data-row-name="${row_name}"]`);
		const $time    = d.$wrapper.find(`.md-start-time[data-row-name="${row_name}"]`);
		const $end     = d.$wrapper.find(`.md-end-display[data-row-name="${row_name}"]`);
		const $bkd     = d.$wrapper.find(`.md-end-breakdown[data-row-name="${row_name}"]`);
		const $sel     = d.$wrapper.find(`.md-mfg-select[data-row-name="${row_name}"]`);
		const $sup_sel = d.$wrapper.find(`.md-supplier-select[data-row-name="${row_name}"]`);

		const date_val = $date.val();
		const time_val = $time.val().trim();

		if (!date_val || !/^\d{2}:\d{2}$/.test(time_val)) return;

		const mfg_type  = $sel.val()     || row.custom_manufacturing_type || '';
		const supplier  = $sup_sel.val() || '';
		const start_str = `${date_val} ${time_val}:00`;

		$end.html('<span style="color:#94a3b8;font-style:italic;font-size:11px;">calculating…</span>');
		$bkd.text('');

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_fg_dates.recalculate_fg_end_date',
			args: {
				planned_start_date: start_str,
				bom_no:             row.bom_no     || '',
				planned_qty:        row.planned_qty || 0,
				manufacturing_type: mfg_type,
				item_code:          row.item_code  || '',
				supplier:           supplier,
			},
			callback(r) {
				const msg     = r.message || {};
				const end_val = msg.custom_planned_end_date;

				if (end_val) {
					try {
						$end.html(frappe.datetime.str_to_user(end_val));
					} catch(e) {
						$end.html(end_val);
					}
					$end.data('raw-end', end_val);   // persist raw ISO value for _apply_changes
				} else {
					$end.html('<span style="color:#cbd5e1;font-style:italic;">—</span>');
				}
				$bkd.text(msg.breakdown || '');
			},
		});
	}

	// ── Recalculate SFG chain dates when FG start date changes ────────────

	/**
	 * Calls calculate_inhouse_schedule_dates for all In-House SFG items
	 * linked to the given FG po_item row, then updates the Step 2 inputs.
	 */
	function _refresh_sfg_dates_for_chain(row_name) {
		if (!has_sfg) return;
		const po_item = po_items.find(r => r.name === row_name);
		if (!po_item) return;

		const $date    = d.$wrapper.find(`.md-start-date[data-row-name="${row_name}"]`);
		const $time    = d.$wrapper.find(`.md-start-time[data-row-name="${row_name}"]`);
		const date_val = $date.val();
		if (!date_val) return;

		const time_val = $time.val().trim();
		const start_str = `${date_val} ${/^\d{2}:\d{2}$/.test(time_val) ? time_val : '10:00'}:00`;

		// Collect all SFG items for this chain in doc order (BOM traversal order)
		const chain_items = sfg_items
			.filter(r => r.production_plan_item === row_name)
			.map(r => ({
				name:                  r.name,
				production_item:       r.production_item,
				parent_item_code:      r.parent_item_code,
				bom_no:                r.bom_no                || '',
				qty:                   r.qty                   || 0,
				type_of_manufacturing: r.type_of_manufacturing || 'In House',
				schedule_date:         r.schedule_date         || '',
			}));

		if (!chain_items.length) return;

		// Dim chain rows while recalculating
		chain_items.forEach(ci => {
			d.$wrapper
				.find(`.md-sfg-sdate[data-sfg-name="${ci.name}"],` +
				      `.md-sfg-stime[data-sfg-name="${ci.name}"],` +
				      `.md-sfg-edate[data-sfg-name="${ci.name}"],` +
				      `.md-sfg-etime[data-sfg-name="${ci.name}"]`)
				.css('opacity', '0.45');
		});

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_sfg_dates.recalculate_sfg_chain_dates',
			args: {
				production_plan_name:   frm.doc.name,
				po_item_name:           row_name,
				new_planned_start_date: start_str,
			},
			callback(r) {
				const results = r.message || {};
				chain_items.forEach(ci => {
					const sfg_rn = ci.name;
					d.$wrapper
						.find(`.md-sfg-sdate[data-sfg-name="${sfg_rn}"],` +
						      `.md-sfg-stime[data-sfg-name="${sfg_rn}"],` +
						      `.md-sfg-edate[data-sfg-name="${sfg_rn}"],` +
						      `.md-sfg-etime[data-sfg-name="${sfg_rn}"]`)
						.css('opacity', '1');

					const dates = results[sfg_rn];
					if (!dates) return;

					d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${sfg_rn}"]`).val(to_date_part(dates.schedule_date));
					d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${sfg_rn}"]`).val(to_time_part(dates.schedule_date));
					d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${sfg_rn}"]`).val(to_date_part(dates.custom_schedule_end_date));
					d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${sfg_rn}"]`).val(to_time_part(dates.custom_schedule_end_date));

					// Flash immediately if Step 2 is visible, otherwise queue for when user navigates there
					if (ALL_STEPS[_step] && ALL_STEPS[_step].id === 'sfg') {
						_flash_sfg_row(sfg_rn);
					} else {
						_pending_sfg_flashes.add(sfg_rn);
					}
				});
				// After all SFG dates are updated, refresh MR dates to match new SFG schedule_dates
				// Pass row_name (= po_items.name) so only this chain's MR rows are updated
				_refresh_mr_from_sfg(row_name);
			},
		});
	}

	// ── Event bindings — FG Step ───────────────────────────────────────────

	// DATE picker: validate then recalculate
	d.$wrapper.on('change', '.md-start-date', function() {
		const rn    = $(this).data('row-name');
		const $time = d.$wrapper.find(`.md-start-time[data-row-name="${rn}"]`);
		_validate_date_change($(this), $time, constraints);
		_refresh_end_date(rn);
		_refresh_sfg_dates_for_chain(rn);
	});

	// TIME input: auto-colon on keystroke
	d.$wrapper.on('input', '.md-start-time', function() {
		let v = $(this).val().replace(/\D/g, '').slice(0, 4);
		if (v.length >= 3) v = v.slice(0, 2) + ':' + v.slice(2);
		$(this).val(v);
	});

	// TIME input: validate on blur, then recalculate
	d.$wrapper.on('blur', '.md-start-time', function() {
		const rn    = $(this).data('row-name');
		const $date = d.$wrapper.find(`.md-start-date[data-row-name="${rn}"]`);
		_validate_time_blur($date, $(this), constraints);
		_refresh_end_date(rn);
		_refresh_sfg_dates_for_chain(rn);
	});

	// Focus ring on FG date/time inputs
	d.$wrapper.on('focusin', '.md-start-date, .md-start-time', function() {
		$(this).css({ 'border-color': '#4f46e5', background: '#fff', 'box-shadow': '0 0 0 3px rgba(79,70,229,0.14)' });
	}).on('focusout', '.md-start-date, .md-start-time', function() {
		$(this).css({ 'border-color': '#c7d2fe', background: '#fafafe', 'box-shadow': 'none' });
	});

	// MFG TYPE: recolor pill + show/hide supplier dropdown + recalculate
	d.$wrapper.on('change', '.md-mfg-select', function() {
		const val = $(this).val();
		const rn  = $(this).data('row-name');
		const bg  = val === 'In House' ? '#dbeafe' : val === 'Subcontract' ? '#fef3c7' : '#f1f5f9';
		const clr = val === 'In House' ? '#1e40af' : val === 'Subcontract' ? '#92400e' : '#64748b';
		$(this).css({ background: bg, color: clr });
		d.$wrapper.find(`.md-supplier-wrap[data-row-name="${rn}"]`).toggle(val === 'Subcontract');
		_refresh_end_date(rn);
	});

	// SUPPLIER: update lead-time hint + recalculate
	d.$wrapper.on('change', '.md-supplier-select', function() {
		const rn   = $(this).data('row-name');
		const lead = $(this).find(':selected').data('lead') || 0;
		d.$wrapper.find(`.md-lead-info[data-row-name="${rn}"]`).text(lead ? `Lead time: ${lead}d` : '');
		_refresh_end_date(rn);
	});

	// ── SFG bidirectional row-level date recalculation ────────────────────

	/**
	 * When user changes either the start OR end date/time of an SFG row,
	 * call the server to compute the other side:
	 *
	 *   changed_field = "schedule_date"            → server returns new end
	 *   changed_field = "custom_schedule_end_date" → server returns new start
	 *
	 * Works for both In House (shift-aware production minutes) and
	 * Subcontract (lead_time + GRN days) rows.
	 */
	function _recalc_sfg_row(sfg_rn, changed_field) {
		const is_start  = changed_field === 'schedule_date';
		const $date     = d.$wrapper.find(`.md-sfg-${is_start ? 'sdate' : 'edate'}[data-sfg-name="${sfg_rn}"]`);
		const $time     = d.$wrapper.find(`.md-sfg-${is_start ? 'stime' : 'etime'}[data-sfg-name="${sfg_rn}"]`);
		const date_val  = $date.val();
		const time_val  = $time.val().trim();
		if (!date_val || !/^\d{2}:\d{2}$/.test(time_val)) return;

		const new_value = `${date_val} ${time_val}:00`;

		// Dim the OTHER side while recalculating
		const $odate = d.$wrapper.find(`.md-sfg-${is_start ? 'edate' : 'sdate'}[data-sfg-name="${sfg_rn}"]`);
		const $otime = d.$wrapper.find(`.md-sfg-${is_start ? 'etime' : 'stime'}[data-sfg-name="${sfg_rn}"]`);
		$odate.css('opacity', '0.45');
		$otime.css('opacity', '0.45');

		// Read current dialog mfg type + supplier to override saved-doc values
		const override_mfg = d.$wrapper.find(`.md-sfg-mfg[data-sfg-name="${sfg_rn}"]`).val()       || '';
		const override_sup = d.$wrapper.find(`.md-sfg-supplier[data-sfg-name="${sfg_rn}"]`).val()   || '';

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_sfg_dates.recalculate_sfg_row_dates',
			args: {
				production_plan_name: frm.doc.name,
				sfg_row_name:         sfg_rn,
				changed_field:        changed_field,
				new_value:            new_value,
				override_mfg_type:    override_mfg,
				override_supplier:    override_sup,
			},
			callback(r) {
				$odate.css('opacity', '1');
				$otime.css('opacity', '1');
				const res = r.message || {};
				if (!res.schedule_date) return;

				// If the backdate guard clamped the start, also update the changed side's inputs
				if (res.clamped) {
					const clamped_val = is_start ? res.schedule_date : res.custom_schedule_end_date;
					$date.val(to_date_part(clamped_val));
					$time.val(to_time_part(clamped_val));
					frappe.show_alert({
						message: __('Start date would be in the past — moved to today. End date pushed forward accordingly.'),
						indicator: 'orange',
					});
				}

				const other_val = is_start ? res.custom_schedule_end_date : res.schedule_date;
				$odate.val(to_date_part(other_val));
				$otime.val(to_time_part(other_val));

				// Cascade new start date DOWN to child SFGs (tight-chain: child.end = parent.start).
				// res.schedule_date is always the start, whether user changed start or end.
				_cascade_sfg_downward(sfg_rn, res.schedule_date);

				// Cascade end-date change upward to ancestors + FG
				_cascade_sfg_upward(sfg_rn);
			},
		});
	}

	// ── SFG upward cascade (called after bidirectional recalc is settled) ─

	/**
	 * When user manually edits an SFG's end date (or end time), push any
	 * ancestor SFGs that can no longer accommodate the new end, and
	 * optionally push the FG's planned_start_date as well.
	 *
	 * Works for any BOM depth (single-level, linear, wide+deep, etc.).
	 */
	function _cascade_sfg_upward(sfg_rn) {
		const $edate = d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${sfg_rn}"]`);
		const $etime = d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${sfg_rn}"]`);
		const edate  = $edate.val();
		const etime  = $etime.val().trim();
		if (!edate || !/^\d{2}:\d{2}$/.test(etime)) return;

		const new_end = `${edate} ${etime}:00`;

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_sfg_dates.recalculate_sfg_chain_upward',
			args: {
				production_plan_name: frm.doc.name,
				changed_sfg_name:     sfg_rn,
				new_end_date:         new_end,
			},
			callback(r) {
				const res         = r.message || {};
				const sfg_updates = res.sfg_updates || {};
				const fg_update   = res.fg_update   || {};
				const sfg_count   = Object.keys(sfg_updates).length;
				const fg_count    = Object.keys(fg_update).length;

				// ── Update ancestor SFG rows + flash them ────────────────
				Object.entries(sfg_updates).forEach(([rn, dates]) => {
					d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`).val(to_date_part(dates.schedule_date));
					d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${rn}"]`).val(to_time_part(dates.schedule_date));
					d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${rn}"]`).val(to_date_part(dates.custom_schedule_end_date));
					d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${rn}"]`).val(to_time_part(dates.custom_schedule_end_date));
					_flash_sfg_row(rn);
				});
				// Pulse the Sub Assembly step indicator
				if (sfg_count > 0) _flash_step_indicator(ALL_STEPS.findIndex(s => s.id === 'sfg'));

				// ── Update FG row in Step 1 + flash it ───────────────────
				Object.entries(fg_update).forEach(([po_name, dates]) => {
					d.$wrapper.find(`.md-start-date[data-row-name="${po_name}"]`).val(to_date_part(dates.planned_start_date));
					d.$wrapper.find(`.md-start-time[data-row-name="${po_name}"]`).val(to_time_part(dates.planned_start_date));
					const $end = d.$wrapper.find(`.md-end-display[data-row-name="${po_name}"]`);
					try {
						$end.html(frappe.datetime.str_to_user(dates.custom_planned_end_date));
					} catch(e) {
						$end.html(dates.custom_planned_end_date);
					}
					$end.data('raw-end', dates.custom_planned_end_date);
					$end.attr('data-raw-end', dates.custom_planned_end_date);
					// Flash FG row directly if on Step 1, otherwise queue + pulse its step indicator
					if (ALL_STEPS[_step] && ALL_STEPS[_step].id === 'fg') {
						_flash_fg_row(po_name);
					} else {
						_pending_fg_flashes.add(po_name);
						_flash_step_indicator(ALL_STEPS.findIndex(s => s.id === 'fg'));
					}
				});

				// ── Alerts ─────────────────────────────────────────────
				if (res.clamped_ancestors) {
					frappe.show_alert({ message: __('Some upstream SFG start dates were in the past — moved to today.'), indicator: 'orange' });
				}
				if (sfg_count > 0 && fg_count > 0) {
					frappe.show_alert({
						message: __(`${sfg_count} sub-assembly item(s) rescheduled. FG Items start date also updated.`),
						indicator: 'blue',
					});
				} else if (sfg_count > 0) {
					frappe.show_alert({
						message: __(`${sfg_count} upstream sub-assembly item(s) rescheduled.`),
						indicator: 'blue',
					});
				} else if (fg_count > 0) {
					frappe.show_alert({
						message: __('FG Items start date updated.'),
						indicator: 'blue',
					});
				}
				// Refresh MR dates to reflect updated SFG schedule_dates
				// Look up po_item_name via sfg_rn so only this chain's MR rows are updated
				const _sfg_for_po = sfg_items.find(r => r.name === sfg_rn);
				_refresh_mr_from_sfg(_sfg_for_po ? _sfg_for_po.production_plan_item : null);
			},
		});
	}

	// ── SFG downward cascade ───────────────────────────────────────────────

	/**
	 * When an SFG's START date changes (because its end was edited and the start
	 * was backward-calculated, or the user changed start directly), cascade DOWN
	 * to every descendant in the same chain.
	 *
	 * Tight-chain rule: child.end = parent.new_start.
	 * Duration is preserved (end − start = constant from current DOM values),
	 * so child.new_start = child.new_end − child_duration → no replanning.
	 *
	 * Pure DOM operation — no API call needed.
	 */
	function _cascade_sfg_downward(sfg_rn, new_start_str) {
		const changed_row = sfg_items.find(r => r.name === sfg_rn);
		if (!changed_row) return;

		const chain_id   = changed_row.production_plan_item;
		const chain_rows = sfg_items.filter(r => r.production_plan_item === chain_id);

		// production_item → [child rows whose parent_item_code == production_item]
		const parent_to_children = {};
		chain_rows.forEach(r => {
			(parent_to_children[r.parent_item_code] = parent_to_children[r.parent_item_code] || []).push(r);
		});

		let any_updated = false;
		// Queue: {pi: production_item_of_current_node, ns: new_start_datetime_str}
		const queue = [{ pi: changed_row.production_item, ns: new_start_str }];

		while (queue.length) {
			const { pi, ns: parent_new_start } = queue.shift();
			const children = parent_to_children[pi] || [];

			children.forEach(child => {
				// Tight chain: child must end exactly when parent starts
				const child_new_end_str = parent_new_start;

				// Read current duration from DOM (reflects any prior edits this session)
				const cs_date = d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${child.name}"]`).val();
				const cs_time = (d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${child.name}"]`).val().trim() || '10:00');
				const ce_date = d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${child.name}"]`).val();
				const ce_time = (d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${child.name}"]`).val().trim() || '10:00');
				if (!cs_date || !ce_date) return;

				const curr_start_dt = _parse_local_dt(`${cs_date} ${cs_time}:00`);
				const curr_end_dt   = _parse_local_dt(`${ce_date} ${ce_time}:00`);
				const child_end_dt  = _parse_local_dt(child_new_end_str);
				if (!curr_start_dt || !curr_end_dt || !child_end_dt) return;

				const duration_ms     = Math.max(curr_end_dt - curr_start_dt, 0);
				const child_start_dt  = new Date(child_end_dt.getTime() - duration_ms);
				const child_new_start_str = _dt_to_str(child_start_dt);

				// Update DOM
				d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${child.name}"]`).val(to_date_part(child_new_start_str));
				d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${child.name}"]`).val(to_time_part(child_new_start_str));
				d.$wrapper.find(`.md-sfg-edate[data-sfg-name="${child.name}"]`).val(to_date_part(child_new_end_str));
				d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${child.name}"]`).val(to_time_part(child_new_end_str));
				_flash_sfg_row(child.name);
				any_updated = true;

				// Continue cascading further down from this child
				queue.push({ pi: child.production_item, ns: child_new_start_str });
			});
		}

		if (any_updated) _flash_step_indicator(ALL_STEPS.findIndex(s => s.id === 'sfg'));
	}

	// ── Event bindings — SFG Step ──────────────────────────────────────────

	// SFG: SCHEDULE START date change — backdate + holiday guard → recalc end
	d.$wrapper.on('change', '.md-sfg-sdate', function() {
		const rn    = $(this).data('sfg-name');
		const $time = d.$wrapper.find(`.md-sfg-stime[data-sfg-name="${rn}"]`);
		_validate_date_change($(this), $time, constraints);
		_recalc_sfg_row(rn, 'schedule_date');
	});

	// SFG: SCHEDULE END date change — holiday guard → recalc start
	d.$wrapper.on('change', '.md-sfg-edate', function() {
		const rn    = $(this).data('sfg-name');
		const $time = d.$wrapper.find(`.md-sfg-etime[data-sfg-name="${rn}"]`);
		_validate_date_change($(this), $time, constraints);
		_recalc_sfg_row(rn, 'custom_schedule_end_date');
	});

	// SFG: auto-colon on time inputs
	d.$wrapper.on('input', '.md-sfg-stime, .md-sfg-etime', function() {
		let v = $(this).val().replace(/\D/g, '').slice(0, 4);
		if (v.length >= 3) v = v.slice(0, 2) + ':' + v.slice(2);
		$(this).val(v);
	});

	// SFG: SCHEDULE START time blur — validate format + shift/lunch → recalc end
	d.$wrapper.on('blur', '.md-sfg-stime', function() {
		const rn    = $(this).data('sfg-name');
		const $date = d.$wrapper.find(`.md-sfg-sdate[data-sfg-name="${rn}"]`);
		_validate_time_blur($date, $(this), constraints);
		_recalc_sfg_row(rn, 'schedule_date');
	});

	// SFG: SCHEDULE END time blur — validate format → recalc start
	d.$wrapper.on('blur', '.md-sfg-etime', function() {
		const rn       = $(this).data('sfg-name');
		const time_val = $(this).val().trim();
		if (!time_val) return;
		if (!/^\d{2}:\d{2}$/.test(time_val)) { $(this).val(''); return; }
		const [h, m] = time_val.split(':').map(Number);
		if (h > 23 || m > 59) { $(this).val(''); return; }
		_recalc_sfg_row(rn, 'custom_schedule_end_date');
	});

	// SFG: MFG TYPE recolor pill + show/hide supplier + recalc
	// Recalcs immediately for In House or Subcontract-with-supplier-already-set.
	// For Subcontract with no supplier yet: just shows the dropdown — recalc fires
	// from the supplier change handler once a supplier is selected.
	d.$wrapper.on('change', '.md-sfg-mfg', function() {
		const rn  = $(this).data('sfg-name');
		const val = $(this).val();
		const bg  = val === 'In House'    ? '#dbeafe'
			      : val === 'Subcontract' ? '#fef3c7'
			      : '#dcfce7';
		const clr = val === 'In House'    ? '#1e40af'
			      : val === 'Subcontract' ? '#92400e'
			      : '#14532d';
		$(this).css({ background: bg, color: clr });
		d.$wrapper.find(`.md-sfg-supplier-wrap[data-sfg-name="${rn}"]`)
			.css('display', val === 'Subcontract' ? 'block' : 'none');
		// Recalc + cascade: always for In House; for Subcontract only when supplier is set
		const has_supplier = !!d.$wrapper.find(`.md-sfg-supplier[data-sfg-name="${rn}"]`).val();
		if (val !== 'Subcontract' || has_supplier) {
			_recalc_sfg_row(rn, 'schedule_date');
		}
	});

	// SFG: SUPPLIER change — recalc dates with new supplier (passes override to server)
	d.$wrapper.on('change', '.md-sfg-supplier', function() {
		const rn = $(this).data('sfg-name');
		_recalc_sfg_row(rn, 'schedule_date');
	});

	// SFG: focus ring on date/time inputs
	d.$wrapper.on('focusin', '.md-sfg-sdate, .md-sfg-stime, .md-sfg-edate, .md-sfg-etime', function() {
		$(this).css({ 'border-color': '#4f46e5', background: '#fff', 'box-shadow': '0 0 0 3px rgba(79,70,229,0.14)' });
	}).on('focusout', '.md-sfg-sdate, .md-sfg-stime, .md-sfg-edate, .md-sfg-etime', function() {
		$(this).css({ 'border-color': '#c7d2fe', background: '#fafafe', 'box-shadow': 'none' });
	});

	// ── Event bindings — MR Step ────────────────────────────────────────────────────

	// MR: START DATE change → backdate guard + auto-calc schedule_date from server
	d.$wrapper.on('change', '.md-mr-sdate', function() {
		const rn    = $(this).data('mr-name');
		const sdate = $(this).val();
		if (!sdate) return;

		// Backdate guard
		const today_str = frappe.datetime.get_today();
		if (!constraints.allow_backdate && sdate < today_str) {
			frappe.show_alert({ message: __('Start date cannot be in the past.'), indicator: 'orange' });
			$(this).val($(this).data('original') || today_str);
			return;
		}
		// Update the stored original so re-validation works
		$(this).data('original', sdate);

		// Auto-calculate schedule_date via server (lead_time + grn_days)
		// Always pass the currently-selected supplier so the server uses the right lead time
		const _sup_rn = d.$wrapper.find(`.md-mr-supplier[data-mr-name="${rn}"]`).val() || '';
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_mr_dates.recalculate_mr_schedule_date',
			args: {
				production_plan_name: frm.doc.name,
				mr_row_name:          rn,
				new_start_date:       sdate,
				supplier_override:    _sup_rn,
			},
			callback(r) {
				const res = r.message || {};
				if (res.schedule_date) {
					const sched = res.schedule_date.slice(0, 10);
					d.$wrapper.find(`.md-mr-edate[data-mr-name="${rn}"]`)
						.val(sched).data('original', sched);
				}
				// Cascade upward, scoped to this chain only
				_propagate_mr_upward(rn);
			},
		});
	});

	// MR: SCHEDULE DATE change — backdate guard only
	d.$wrapper.on('change', '.md-mr-edate', function() {
		const rn    = $(this).data('mr-name');
		const sdate = $(this).val();
		if (!sdate) return;
		const today_str = frappe.datetime.get_today();
		if (!constraints.allow_backdate && sdate < today_str) {
			frappe.show_alert({ message: __('Schedule date cannot be in the past.'), indicator: 'orange' });
			$(this).val($(this).data('original') || today_str);
			return;
		}
		$(this).data('original', sdate);
		// Cascade upward, scoped to this chain
		_propagate_mr_upward(rn);
	});

	// MR: SUPPLIER change — recalculate schedule_date with new supplier's lead time
	d.$wrapper.on('change', '.md-mr-supplier', function() {
		const rn    = $(this).data('mr-name');
		const sup   = $(this).val();
		const sdate = d.$wrapper.find(`.md-mr-sdate[data-mr-name="${rn}"]`).val();
		if (!sdate) return;
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.overrides.pp_mr_dates.recalculate_mr_schedule_date',
			args: {
				production_plan_name: frm.doc.name,
				mr_row_name:          rn,
				new_start_date:       sdate,
				supplier_override:    sup,
			},
			callback(r) {
				const res = r.message || {};
				if (res.schedule_date) {
					const sched = res.schedule_date.slice(0, 10);
					d.$wrapper.find(`.md-mr-edate[data-mr-name="${rn}"]`)
						.val(sched).data('original', sched);
				}
				_propagate_mr_upward(rn);
			},
		});
	});

	// MR: focus ring on date inputs
	d.$wrapper.on('focusin', '.md-mr-sdate, .md-mr-edate', function() {
		$(this).css({ 'border-color': '#7c3aed', background: '#fff', 'box-shadow': '0 0 0 3px rgba(124,58,237,0.14)' });
	}).on('focusout', '.md-mr-sdate, .md-mr-edate', function() {
		$(this).css({ 'border-color': '#ddd6fe', background: '#fafafe', 'box-shadow': 'none' });
	});
}
