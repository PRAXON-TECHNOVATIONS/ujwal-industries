frappe.pages['machine_production_display'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Machine Production Display',
		single_column: true,
	});

	new MachineProductionDisplay(wrapper, page);
};

const STATUS_CFG = {
	'Work In Progress':     { color: '#16a34a', bg: '#dcfce7', label: 'In Progress'    },
	'Open':                 { color: '#d97706', bg: '#fef3c7', label: 'Open'           },
	'On Hold':              { color: '#dc2626', bg: '#fee2e2', label: 'On Hold'        },
	'Material Transferred': { color: '#2563eb', bg: '#dbeafe', label: 'Material Ready' },
};

function statusCfg(s) {
	return STATUS_CFG[s] || { color: '#6b7280', bg: '#f3f4f6', label: s || '—' };
}

function fmtDt(dt) {
	if (!dt) return '—';
	const d = new Date(dt);
	const p = n => String(n).padStart(2, '0');
	return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`;
}

function mpdLink(doctype, name) {
	if (!name) return '—';
	const route = frappe.utils.get_form_link(doctype, name);
	return `<a href="${route}" class="mpd-link">${frappe.utils.escape_html(name)}</a>`;
}

class MachineProductionDisplay {
	constructor(wrapper, page) {
		this.wrapper    = wrapper;
		this.page       = page;
		this.rows       = [];
		this.PAGE_SIZE  = 10;     // rows per page
		this.PAGE_DWELL = 30;    // seconds on each page before auto-advance
		this.DATA_REFRESH = 60; // seconds before re-fetching from server

		this._curPage   = 0;    // current page index (0-based)
		this._dataTimer = null; // countdown to next server fetch
		this._pageTimer = null; // countdown to next auto page-flip
		this._paused    = false;

		this._init();
	}

	_init() {
		this._injectStyles();
		this._buildToolbar();
		this._shrinkPageHeader();

		this.$root = $(`<div id="mpd-root"></div>`)
			.appendTo($(this.wrapper).find('.page-content'));

		this._load();
	}

	// ── Toolbar ───────────────────────────────────────────────────────────────
	_buildToolbar() {
		this.page.add_inner_button('Refresh Now', () => this._load());

		// Pause / Resume auto-scroll
		this.$pauseBtn = $(
			`<button class="btn btn-xs btn-default" id="mpd-pause-btn" style="margin-left:8px;">⏸ Pause</button>`
		).appendTo(this.page.inner_toolbar);
		this.$pauseBtn.on('click', () => this._togglePause());

		// Data refresh countdown
		$(`<span id="mpd-data-cd" style="font-size:12px;color:#6b7280;margin-left:12px;">
			Data refresh in <b id="mpd-data-num">${this.DATA_REFRESH}</b>s
		</span>`).appendTo(this.page.inner_toolbar);
	}

	// ── Shrink Frappe's default page header (title, buttons, spacing) ──────────
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

	// ── Data load ─────────────────────────────────────────────────────────────
	_load() {
		this._stopDataTimer();
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.page.machine_production_display.machine_production_display.get_machine_production_data',
			callback: r => {
				this.rows = [];
				(r.message || []).forEach(m => (m.jobs || []).forEach(j => this.rows.push(j)));
				// stay on current page if still valid, else reset to 0
				const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
				if (this._curPage >= totalPages) this._curPage = 0;
				this._renderPage();
				this._startDataCountdown();
			},
		});
	}

	// ── Page render ───────────────────────────────────────────────────────────
	_renderPage() {
		this.$root.empty();

		const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
		const start      = this._curPage * this.PAGE_SIZE;
		const pageRows   = this.rows.slice(start, start + this.PAGE_SIZE);
		const now        = new Date().toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit', second:'2-digit' });

		// ── info bar ──
		this.$root.append(`
		<div id="mpd-info">
			<span>${this.rows.length} active job card(s) &nbsp;|&nbsp; Last updated: ${now}</span>
		</div>`);

		if (!this.rows.length) {
			this.$root.append(`<div class="mpd-empty">No active job cards found</div>`);
			return;
		}

		// ── table ──
		const colgroup = `
		<colgroup>
			<col style="width:45px">
			<col style="width:90px">
			<col style="width:140px">
			<col style="width:70px">
			<col style="width:200px">
			<col style="width:95px">
			<col style="width:95px">
			<col style="width:95px">
			<col style="width:95px">
			<col style="width:100px">
			<col style="width:120px">
			<col style="width:170px">
		</colgroup>`;

		const thead = `
		<thead><tr>
			<th>#</th>
			<th>Machine No</th>
			<th>Machine Name</th>
			<th>Item Code</th>
			<th>Item Name</th>
			<th>Planned Start</th>
			<th>Actual Start</th>
			<th>Planned End</th>
			<th>Qty (Done / Plan)</th>
			<th>Status</th>
			<th>Pause Reason</th>
			<th>Work Order</th>
		</tr></thead>`;

		const tbody = pageRows.map((j, i) => {
			const cfg     = statusCfg(j.status);
			const startDt = j.expected_start_date || j.wo_planned_start;
			const endDt   = j.expected_end_date   || j.wo_planned_end;
			const globalN = start + i + 1;
			return `
			<tr data-status="${j.status || ''}">
				<td class="mpd-num">${globalN}</td>
				<td class="mpd-machine">${frappe.utils.escape_html(j.machine_no || '—')}</td>
				<td class="mpd-machinename">${frappe.utils.escape_html(j.machine_name || '—')}</td>
				<td>${mpdLink('Item', j.item_code)}</td>
				<td class="mpd-itemname">${frappe.utils.escape_html(j.item_name || '—')}</td>
				<td>${fmtDt(startDt)}</td>
				<td>${fmtDt(j.actual_start_date)}</td>
				<td>${fmtDt(endDt)}</td>
				<td class="mpd-qty">${(j.completed_qty||0).toLocaleString()} / ${(j.planned_qty||0).toLocaleString()}</td>
				<td class="mpd-status"><span class="mpd-badge" style="color:${cfg.color};background:${cfg.bg}">${cfg.label}</span></td>
				<td class="mpd-pausereason">${frappe.utils.escape_html(j.pause_reason || '—')}</td>
				<td>${mpdLink('Work Order', j.work_order)}</td>
			</tr>`;
		}).join('');

		this.$root.append(`
		<div class="mpd-table-wrap">
			<table class="mpd-table">${colgroup}${thead}<tbody>${tbody}</tbody></table>
		</div>`);

		// ── pagination bar ──
		const dots = Array.from({ length: totalPages }, (_, i) =>
			`<span class="mpd-dot ${i === this._curPage ? 'active' : ''}" data-page="${i}"></span>`
		).join('');

		this.$root.append(`
		<div id="mpd-pager">
			<button class="mpd-page-btn" id="mpd-prev">&#8592; Prev</button>
			<div id="mpd-dots">${dots}</div>
			<span id="mpd-page-label">Page ${this._curPage + 1} of ${totalPages}</span>
			<div id="mpd-page-bar-wrap"><div id="mpd-page-bar"></div></div>
			<button class="mpd-page-btn" id="mpd-next">Next &#8594;</button>
		</div>`);

		// dot click → jump to page
		this.$root.find('.mpd-dot').on('click', e => {
			this._curPage = parseInt($(e.target).data('page'));
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#mpd-prev').on('click', () => {
			this._curPage = (this._curPage - 1 + totalPages) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#mpd-next').on('click', () => {
			this._curPage = (this._curPage + 1) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		// start progress bar animation + page auto-advance
		if (!this._paused) this._startPageTimer(totalPages);
	}

	// ── Page auto-advance timer ───────────────────────────────────────────────
	_startPageTimer(totalPages) {
		this._stopPageTimer();
		const bar = () => document.getElementById('mpd-page-bar');

		// reset bar
		if (bar()) { bar().style.transition = 'none'; bar().style.width = '0%'; }

		// small tick to let CSS reset apply, then animate
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

	// ── Pause / Resume ────────────────────────────────────────────────────────
	_togglePause() {
		this._paused = !this._paused;
		this.$pauseBtn.text(this._paused ? '▶ Resume' : '⏸ Pause');
		if (this._paused) {
			this._stopPageTimer();
			const bar = document.getElementById('mpd-page-bar');
			if (bar) { bar.style.transition = 'none'; bar.style.width = '0%'; }
		} else {
			const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
			this._startPageTimer(totalPages);
		}
	}

	// ── Data refresh countdown ────────────────────────────────────────────────
	_startDataCountdown() {
		let rem = this.DATA_REFRESH;
		const el = () => document.getElementById('mpd-data-num');
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

	// ── Styles ────────────────────────────────────────────────────────────────
	_injectStyles() {
		if (document.getElementById('mpd-styles')) return;
		const s = document.createElement('style');
		s.id = 'mpd-styles';
		s.textContent = `
#mpd-root {
	padding: 0 20px 10px;
	font-family: 'Segoe UI', system-ui, sans-serif;
}

#mpd-info {
	display: flex;
	justify-content: space-between;
	font-size: 11px;
	color: #6b7280;
	margin: 0 0 4px;
}

/* ── Table ── */
.mpd-table-wrap {
	overflow-x: auto;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
}
.mpd-table {
	min-width: 1280px;
	width: 1280px;
	table-layout: fixed;
	border-collapse: collapse;
	font-size: 13px;
	color: #111827;
}
.mpd-table thead tr { height: 45px; }
.mpd-table thead th {
	background: #f9fafb;
	height: 45px;
	max-height: 45px;
	padding: 4px 12px;
	text-align: left;
	font-size: 13px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.5px;
	color: #374151;
	border-bottom: 2px solid #e5e7eb;
	border-right: 1px solid #e5e7eb;
	white-space: normal;
	word-break: break-word;
	overflow: hidden;
	text-overflow: clip;
	vertical-align: middle;
	line-height: 1.2;
	box-sizing: border-box;
}
.mpd-table thead th:last-child { border-right: none; }
.mpd-table tbody tr { height: 45px; }
.mpd-table tbody td {
	height: 45px;
	max-height: 45px;
	padding: 4px 12px;
	border-bottom: 1px solid #f3f4f6;
	border-right: 1px solid #f0f0f0;
	vertical-align: middle;
	overflow: hidden;
	text-overflow: ellipsis;
	box-sizing: border-box;
	white-space: nowrap;
}
.mpd-table tbody td:last-child  { border-right: none; }
.mpd-table tbody tr:last-child td { border-bottom: none; }
.mpd-table tbody tr:hover td    { background: #f9fafb; }

/* status colour bar on Machine No column (first data column) */
.mpd-table tbody tr[data-status="Work In Progress"]    td:nth-child(2) { border-left: 4px solid #16a34a; }
.mpd-table tbody tr[data-status="On Hold"]             td:nth-child(2) { border-left: 4px solid #dc2626; }
.mpd-table tbody tr[data-status="Open"]                td:nth-child(2) { border-left: 4px solid #d97706; }
.mpd-table tbody tr[data-status="Material Transferred"] td:nth-child(2) { border-left: 4px solid #2563eb; }

.mpd-num      { color: #9ca3af; width: 36px; }
.mpd-machine  { font-weight: 400; }
.mpd-qty,
.mpd-itemname,
.mpd-pausereason,
.mpd-machinename {
	white-space: normal !important;
	word-break: break-word;
	overflow-wrap: break-word;
	overflow: hidden !important;
	text-overflow: clip !important;
	display: -webkit-box;
	-webkit-line-clamp: 2;
	-webkit-box-orient: vertical;
	line-height: 1.15;
}
.mpd-qty { font-variant-numeric: tabular-nums; }

.mpd-link {
	color: #111827;
	font-weight: 400;
	text-decoration: none;
	white-space: nowrap;
}
.mpd-link:hover { text-decoration: underline; }

.mpd-status { white-space: normal !important; }
.mpd-badge {
	display: inline-block;
	padding: 2px 10px;
	border-radius: 20px;
	font-weight: 400;
	letter-spacing: 0.5px;
	white-space: normal;
}

/* ── Pagination bar ── */
#mpd-pager {
	display: flex;
	align-items: center;
	gap: 12px;
	margin-top: 10px;
	flex-wrap: wrap;
}

.mpd-page-btn {
	padding: 5px 14px;
	font-size: 12px;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	background: #fff;
	cursor: pointer;
	color: #374151;
}
.mpd-page-btn:hover { background: #f3f4f6; }

#mpd-dots {
	display: flex;
	gap: 6px;
	align-items: center;
}
.mpd-dot {
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: #d1d5db;
	cursor: pointer;
	transition: background 0.2s, transform 0.2s;
}
.mpd-dot.active {
	background: #2563eb;
	transform: scale(1.35);
}
.mpd-dot:hover { background: #9ca3af; }

#mpd-page-label {
	font-size: 12px;
	color: #6b7280;
	white-space: nowrap;
}

/* progress bar — shows time until next page flip */
#mpd-page-bar-wrap {
	flex: 1;
	height: 4px;
	background: #e5e7eb;
	border-radius: 2px;
	overflow: hidden;
	min-width: 80px;
}
#mpd-page-bar {
	height: 100%;
	width: 0%;
	background: #2563eb;
	border-radius: 2px;
}

.mpd-empty {
	text-align: center;
	padding: 60px;
	color: #9ca3af;
	font-size: 15px;
}
		`;
		document.head.appendChild(s);
	}
}
