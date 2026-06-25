frappe.pages['store_display'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Store Display',
		single_column: true,
	});

	new StoreDisplay(wrapper, page);
};

const STATUS_CFG = {
	'Draft':            { color: '#6b7280', bg: '#f3f4f6', label: 'Draft'           },
	'Not Started':      { color: '#7c3aed', bg: '#ede9fe', label: 'Not Started'     },
	'Open':             { color: '#d97706', bg: '#fef3c7', label: 'Open'            },
	'Work In Progress': { color: '#16a34a', bg: '#dcfce7', label: 'In Process'      },
	'Material Return':  { color: '#dc2626', bg: '#fee2e2', label: 'Material Return' },
	'On Hold':          { color: '#dc2626', bg: '#fee2e2', label: 'On Hold'         },
	'Completed':        { color: '#2563eb', bg: '#dbeafe', label: 'Completed'      },
};

function statusCfg(s) {
	const first = (s || '').split(',')[0].trim();
	return STATUS_CFG[first] || { color: '#6b7280', bg: '#f3f4f6', label: s || '—' };
}

function fmtDt(dt) {
	if (!dt) return '—';
	const d = new Date(dt);
	const p = n => String(n).padStart(2, '0');
	return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`;
}

function sdLink(doctype, name) {
	if (!name) return '—';
	const route = frappe.utils.get_form_link(doctype, name);
	return `<a href="${route}" class="sd-link">${frappe.utils.escape_html(name)}</a>`;
}

function num(n) {
	return (n || 0).toLocaleString();
}

function delayBadge(d) {
	if (d === null || d === undefined) return '—';
	const cls = d > 0 ? 'sd-delay-late' : 'sd-delay-ok';
	return `<span class="sd-delay ${cls}">${Math.abs(d)}d</span>`;
}

class StoreDisplay {
	constructor(wrapper, page) {
		this.wrapper      = wrapper;
		this.page         = page;
		this.rows         = [];
		this.PAGE_SIZE    = 10;
		this.PAGE_DWELL   = 30;
		this.DATA_REFRESH = 60;

		this._curPage   = 0;
		this._dataTimer = null;
		this._pageTimer = null;
		this._paused    = false;

		this._init();
	}

	_init() {
		this._injectStyles();
		this._buildToolbar();
		this._shrinkPageHeader();

		this.$root = $(`<div id="sd-root"></div>`)
			.appendTo($(this.wrapper).find('.page-content'));

		this._load();
	}

	_buildToolbar() {
		this.page.add_inner_button('Refresh Now', () => this._load());

		this.$pauseBtn = $(
			`<button class="btn btn-xs btn-default" id="sd-pause-btn" style="margin-left:8px;">⏸ Pause</button>`
		).appendTo(this.page.inner_toolbar);
		this.$pauseBtn.on('click', () => this._togglePause());

		$(`<span id="sd-data-cd" style="font-size:12px;color:#6b7280;margin-left:12px;">
			Data refresh in <b id="sd-data-num">${this.DATA_REFRESH}</b>s
		</span>`).appendTo(this.page.inner_toolbar);
	}

	_shrinkPageHeader() {
		const $w = $(this.wrapper);
		$w.find('.page-head').css({ 'margin-bottom': '0', 'min-height': 'auto', 'padding-bottom': '4px' });
		$w.find('.page-content').css({ 'padding-top': '0', 'margin-top': '0' });
		$w.find('.container').css('padding-top', '0');
		$w.find('.page-title .title-text, .page-title h1, .title-area .title-text')
			.css({ 'font-size': '15px', 'line-height': '1.1', 'margin': '0' });
		$w.find('.page-actions .btn, .custom-actions .btn').css({
			'font-size': '11px',
			'padding': '2px 8px',
			'line-height': '1.3',
		});
		$w.find('.page-actions, .custom-actions').css('margin-top', '0');
		$w.find('.page-head-content').css({ 'margin-bottom': '0', 'padding-bottom': '0' });
		$w.find('.standard-sidebar-section, .page-form').css('display', 'none');
	}

	_load() {
		this._stopDataTimer();
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.page.store_display.store_display.get_store_display_data',
			callback: r => {
				this.rows = r.message || [];
				const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
				if (this._curPage >= totalPages) this._curPage = 0;
				this._renderPage();
				this._startDataCountdown();
			},
		});
	}

	_renderPage() {
		this.$root.empty();

		const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
		const start       = this._curPage * this.PAGE_SIZE;
		const pageRows    = this.rows.slice(start, start + this.PAGE_SIZE);
		const now         = new Date().toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit', second:'2-digit' });

		this.$root.append(`
		<div id="sd-info">
			<span>${this.rows.length} active work order(s) &nbsp;|&nbsp; Last updated: ${now}</span>
		</div>`);

		if (!this.rows.length) {
			this.$root.append(`<div class="sd-empty">No active work orders found</div>`);
			return;
		}

		const colgroup = `
		<colgroup>
			<col style="width:2.5%">
			<col style="width:4%">
			<col style="width:5%">
			<col style="width:5%">
			<col style="width:4.5%">
			<col style="width:6.5%">
			<col style="width:4.5%">
			<col style="width:6.5%">
			<col style="width:4.5%">
			<col style="width:5%">
			<col style="width:5%">
			<col style="width:5%">
			<col style="width:5%">
			<col style="width:4.5%">
			<col style="width:4.5%">
			<col style="width:4%">
			<col style="width:4%">
			<col style="width:6%">
			<col style="width:3.5%">
		</colgroup>`;

		const thead = `
		<thead><tr>
			<th>#</th>
			<th>Work Order</th>
			<th>WO Start Date</th>
			<th>WO End Date</th>
			<th>Part No</th>
			<th>Part Name</th>
			<th>Raw Material No</th>
			<th>Raw Material Name</th>
			<th>WO Qty</th>
			<th>WO Received Qty</th>
			<th>JO Qty Manufactured</th>
			<th>Balance Counting Qty</th>
			<th>Balance to Confirm</th>
			<th>Material Required Qty</th>
			<th>Material Issued Qty</th>
			<th>Scrap Qty</th>
			<th>Scrap Rec. Qty</th>
			<th>JO Status</th>
			<th>Delay (Days)</th>
		</tr></thead>`;

		const tbody = pageRows.map((w, i) => {
			const cfg     = statusCfg(w.jo_status);
			const globalN = start + i + 1;
			return `
			<tr data-status="${(w.jo_status || '').split(',')[0].trim()}">
				<td class="sd-num">${globalN}</td>
				<td>${sdLink('Work Order', w.work_order)}</td>
				<td>${fmtDt(w.wo_start_date)}</td>
				<td>${fmtDt(w.wo_end_date)}</td>
				<td>${sdLink('Item', w.part_no)}</td>
				<td class="sd-wrap">${frappe.utils.escape_html(w.part_name || '—')}</td>
				<td class="sd-wrap">${frappe.utils.escape_html(w.raw_material_no || '—')}</td>
				<td class="sd-wrap">${frappe.utils.escape_html(w.raw_material_name || '—')}</td>
				<td class="sd-qty">${num(w.wo_qty)}</td>
				<td class="sd-qty">${num(w.wo_received_qty)}</td>
				<td class="sd-qty">${num(w.manufactured_qty)}</td>
				<td class="sd-qty">${num(w.balance_counting_qty)}</td>
				<td class="sd-qty">${num(w.balance_to_confirm)}</td>
				<td class="sd-qty">${num(w.material_required_qty)}</td>
				<td class="sd-qty">${num(w.material_issued_qty)}</td>
				<td class="sd-qty">${num(w.scrap_qty)}</td>
				<td class="sd-qty">${num(w.scrap_rec_qty)}</td>
				<td class="sd-status"><span class="sd-badge" style="color:${cfg.color};background:${cfg.bg}">${frappe.utils.escape_html(w.jo_status || cfg.label)}</span></td>
				<td class="sd-qty">${delayBadge(w.delay_in_days)}</td>
			</tr>`;
		}).join('');

		this.$root.append(`
		<div class="sd-table-wrap">
			<table class="sd-table">${colgroup}${thead}<tbody>${tbody}</tbody></table>
		</div>`);

		const dots = Array.from({ length: totalPages }, (_, i) =>
			`<span class="sd-dot ${i === this._curPage ? 'active' : ''}" data-page="${i}"></span>`
		).join('');

		this.$root.append(`
		<div id="sd-pager">
			<button class="sd-page-btn" id="sd-prev">&#8592; Prev</button>
			<div id="sd-dots">${dots}</div>
			<span id="sd-page-label">Page ${this._curPage + 1} of ${totalPages}</span>
			<div id="sd-page-bar-wrap"><div id="sd-page-bar"></div></div>
			<button class="sd-page-btn" id="sd-next">Next &#8594;</button>
		</div>`);

		this.$root.find('.sd-dot').on('click', e => {
			this._curPage = parseInt($(e.target).data('page'));
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#sd-prev').on('click', () => {
			this._curPage = (this._curPage - 1 + totalPages) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#sd-next').on('click', () => {
			this._curPage = (this._curPage + 1) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		if (!this._paused) this._startPageTimer(totalPages);
	}

	_startPageTimer(totalPages) {
		this._stopPageTimer();
		const bar = () => document.getElementById('sd-page-bar');

		if (bar()) { bar().style.transition = 'none'; bar().style.width = '0%'; }

		setTimeout(() => {
			if (bar()) {
				bar().style.transition = `width ${this.PAGE_DWELL}s linear`;
				bar().style.width = '100%';
			}
		}, 50);

		this._pageTimer = setTimeout(() => {
			this._curPage = (this._curPage + 1) % totalPages;
			this._renderPage();
		}, this.PAGE_DWELL * 1000);
	}

	_stopPageTimer() {
		if (this._pageTimer) clearTimeout(this._pageTimer);
	}

	_resetPageTimer() {
		this._stopPageTimer();
		if (!this._paused) {
			const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
			this._startPageTimer(totalPages);
		}
	}

	_togglePause() {
		this._paused = !this._paused;
		this.$pauseBtn.text(this._paused ? '▶ Resume' : '⏸ Pause');
		if (this._paused) {
			this._stopPageTimer();
			const bar = document.getElementById('sd-page-bar');
			if (bar) { bar.style.transition = 'none'; bar.style.width = '0%'; }
		} else {
			const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
			this._startPageTimer(totalPages);
		}
	}

	_startDataCountdown() {
		let rem = this.DATA_REFRESH;
		const el = () => document.getElementById('sd-data-num');
		if (el()) el().textContent = rem;
		this._dataTimer = setInterval(() => {
			rem--;
			if (el()) el().textContent = rem;
			if (rem <= 0) { this._stopDataTimer(); this._load(); }
		}, 1000);
	}

	_stopDataTimer() {
		if (this._dataTimer) clearInterval(this._dataTimer);
	}

	_injectStyles() {
		if (document.getElementById('sd-styles')) return;
		const s = document.createElement('style');
		s.id = 'sd-styles';
		s.textContent = `
#sd-root {
	padding: 0 20px 10px;
	font-family: 'Segoe UI', system-ui, sans-serif;
}

#sd-info {
	display: flex;
	justify-content: space-between;
	font-size: 9px;
	color: #6b7280;
	margin: 0 0 4px;
}

.sd-table-wrap {
	overflow-x: auto;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
}
.sd-table {
	width: 100%;
	min-width: 1280px;
	table-layout: fixed;
	border-collapse: collapse;
	font-size: 11px;
	color: #111827;
}
.sd-table thead tr { height: 45px; }
.sd-table thead th {
	background: #f9fafb;
	padding: 4px 6px;
	text-align: left;
	font-size: 11px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.5px;
	color: #374151;
	border-bottom: 2px solid #e5e7eb;
	border-right: 1px solid #e5e7eb;
	white-space: normal;
	word-break: break-word;
	overflow: hidden;
	vertical-align: middle;
	line-height: 1.2;
	box-sizing: border-box;
}
.sd-table thead th:last-child { border-right: none; }
.sd-table tbody tr { height: 44px; }
.sd-table tbody td {
	height: 45px;
	max-height: 45px;
	padding: 2px 3px;
	border-bottom: 1px solid #f3f4f6;
	border-right: 1px solid #f0f0f0;
	vertical-align: middle;
	box-sizing: border-box;
	white-space: normal;
	word-break: break-word;
	overflow-wrap: break-word;
	overflow: hidden;
	line-height: 1.2;
}
.sd-table tbody td:last-child  { border-right: none; }
.sd-table tbody tr:last-child td { border-bottom: none; }
.sd-table tbody tr:hover td    { background: #f9fafb; }

.sd-table tbody tr[data-status="Work In Progress"] td:nth-child(2) { border-left: 4px solid #16a34a; }
.sd-table tbody tr[data-status="On Hold"]          td:nth-child(2) { border-left: 4px solid #dc2626; }
.sd-table tbody tr[data-status="Open"]             td:nth-child(2) { border-left: 4px solid #d97706; }
.sd-table tbody tr[data-status="Material Return"]  td:nth-child(2) { border-left: 4px solid #dc2626; }
.sd-table tbody tr[data-status="Completed"]        td:nth-child(2) { border-left: 4px solid #2563eb; }

.sd-num  { color: #9ca3af; width: 36px; }
.sd-wrap {
	white-space: normal;
	word-break: break-word;
	overflow-wrap: break-word;
	line-height: 1.25;
}
.sd-qty { font-variant-numeric: tabular-nums; white-space: nowrap; }

.sd-link {
	color: #111827;
	font-weight: 400;
	text-decoration: none;
	word-break: break-word;
}
.sd-link:hover { text-decoration: underline; }

.sd-status { white-space: normal !important; }
.sd-badge {
	display: inline-block;
	padding: 2px 10px;
	border-radius: 20px;
	font-weight: 400;
	letter-spacing: 0.5px;
	white-space: normal;
	font-size: 11px;
}

.sd-delay {
	display: inline-block;
	padding: 2px 8px;
	border-radius: 20px;
	font-weight: 600;
	font-size: 11px;
	white-space: nowrap;
}
.sd-delay-late { color: #dc2626; background: #fee2e2; }
.sd-delay-ok   { color: #16a34a; background: #dcfce7; }

#sd-pager {
	display: flex;
	align-items: center;
	gap: 12px;
	margin-top: 10px;
	flex-wrap: wrap;
}

.sd-page-btn {
	padding: 5px 14px;
	font-size: 12px;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	background: #fff;
	cursor: pointer;
	color: #374151;
}
.sd-page-btn:hover { background: #f3f4f6; }

#sd-dots {
	display: flex;
	gap: 6px;
	align-items: center;
}
.sd-dot {
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: #d1d5db;
	cursor: pointer;
	transition: background 0.2s, transform 0.2s;
}
.sd-dot.active {
	background: #2563eb;
	transform: scale(1.35);
}
.sd-dot:hover { background: #9ca3af; }

#sd-page-label {
	font-size: 12px;
	color: #6b7280;
	white-space: nowrap;
}

#sd-page-bar-wrap {
	flex: 1;
	height: 4px;
	background: #e5e7eb;
	border-radius: 2px;
	overflow: hidden;
	min-width: 80px;
}
#sd-page-bar {
	height: 100%;
	width: 0%;
	background: #2563eb;
	border-radius: 2px;
}

.sd-empty {
	text-align: center;
	padding: 60px;
	color: #9ca3af;
	font-size: 15px;
}
		`;
		document.head.appendChild(s);
	}
}
