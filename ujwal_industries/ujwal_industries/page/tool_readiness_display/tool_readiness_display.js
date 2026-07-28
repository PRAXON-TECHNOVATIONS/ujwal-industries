frappe.pages['tool_readiness_display'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Tool Readiness Display',
		single_column: true,
	});

	new ToolReadinessDisplay(wrapper, page);
};

const STATUS_CFG = {
	'Under Maintenance':    { color: '#ffffff', bg: '#b91c1c', border: '#7f1d1d' },
	'Production Completed': { color: '#3f2d00', bg: '#eab308', border: '#a16207' },
	'Ready for Production': { color: '#ffffff', bg: '#15803d', border: '#14532d' },
};

function statusCfg(s) {
	return STATUS_CFG[s] || { color: '#ffffff', bg: '#4b5563', border: '#1f2937' };
}

// Remaining-days severity band: <=7 urgent (red), 8-14 warning (yellow), >14 fine (green).
function daysCfg(d) {
	if (d === null || d === undefined) return { color: '#6b7280', bg: '#f3f4f6', label: '—' };
	if (d <= 7) return { color: '#ffffff', bg: '#b91c1c', label: `${d}d` };
	if (d <= 14) return { color: '#3f2d00', bg: '#eab308', label: `${d}d` };
	return { color: '#ffffff', bg: '#15803d', label: `${d}d` };
}

function fmtDt(dt) {
	if (!dt) return '—';
	const d = new Date(dt);
	const p = n => String(n).padStart(2, '0');
	return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`;
}

function trdLink(doctype, name) {
	if (!name) return '—';
	const route = frappe.utils.get_form_link(doctype, name);
	return `<a href="${route}" class="trd-link">${frappe.utils.escape_html(name)}</a>`;
}

class ToolReadinessDisplay {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.rows = [];
		this.PAGE_SIZE = 10;
		this.PAGE_DWELL = 30;
		this.DATA_REFRESH = 60;

		this._curPage = 0;
		this._dataTimer = null;
		this._pageTimer = null;
		this._paused = false;

		this._init();
	}

	_init() {
		this._injectStyles();
		this._buildToolbar();
		this._shrinkPageHeader();

		this.$root = $(`<div id="trd-root"></div>`).appendTo($(this.wrapper).find('.page-content'));

		this._load();
	}

	_buildToolbar() {
		this.page.add_inner_button('Refresh Now', () => this._load());

		this.$pauseBtn = $(
			`<button class="btn btn-xs btn-default" id="trd-pause-btn" style="margin-left:8px;">⏸ Pause</button>`
		).appendTo(this.page.inner_toolbar);
		this.$pauseBtn.on('click', () => this._togglePause());

		$(`<span id="trd-data-cd" style="font-size:12px;color:#6b7280;margin-left:12px;">
			Data refresh in <b id="trd-data-num">${this.DATA_REFRESH}</b>s
		</span>`).appendTo(this.page.inner_toolbar);
	}

	_shrinkPageHeader() {
		const $w = $(this.wrapper);
		$w.find('.page-head').css({ 'margin-bottom': '0', 'min-height': 'auto', 'padding-bottom': '4px' });
		$w.find('.page-content').css({ 'padding-top': '0', 'margin-top': '0' });
		$w.find('.container').css('padding-top', '0');
		$w.find('.page-title .title-text, .page-title h1, .title-area .title-text').css({
			'font-size': '15px',
			'line-height': '1.1',
			'margin': '0',
		});
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
			method: 'ujwal_industries.ujwal_industries.page.tool_readiness_display.tool_readiness_display.get_tool_readiness_data',
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
		const start = this._curPage * this.PAGE_SIZE;
		const pageRows = this.rows.slice(start, start + this.PAGE_SIZE);
		const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

		this.$root.append(`
		<div id="trd-info">
			<span>${this.rows.length} tool(s) tracked &nbsp;|&nbsp; Last updated: ${now}</span>
		</div>`);

		if (!this.rows.length) {
			this.$root.append(`<div class="trd-empty">No tools found for open Production Plans</div>`);
			return;
		}

		const colgroup = `
		<colgroup>
			<col style="width:45px">
			<col style="width:100px">
			<col style="width:220px">
			<col style="width:90px">
			<col style="width:110px">
			<col style="width:220px">
			<col style="width:190px">
			<col style="width:140px">
		</colgroup>`;

		const thead = `
		<thead><tr>
			<th>#</th>
			<th>FG Part No</th>
			<th>Item Name</th>
			<th>Part No</th>
			<th>PP Start Date</th>
			<th>Tool Name</th>
			<th>Current Tool Status</th>
			<th>Remaining Days</th>
		</tr></thead>`;

		const tbody = pageRows
			.map((row, i) => {
				const cfg = statusCfg(row.status);
				const dCfg = daysCfg(row.remaining_days);
				const globalN = start + i + 1;
				return `
				<tr>
					<td class="trd-num">${globalN}</td>
					<td>${trdLink('Item', row.fg_part_no)}</td>
					<td class="trd-wrap">${frappe.utils.escape_html(row.item_name || '—')}</td>
					<td>${frappe.utils.escape_html(row.part_no || '—')}</td>
					<td>${fmtDt(row.pp_start_date)}</td>
					<td class="trd-wrap">${trdLink('Asset', row.tool)}</td>
					<td class="trd-status"><span class="trd-badge" style="color:${cfg.color};background:${cfg.bg}">${frappe.utils.escape_html(row.status)}</span></td>
					<td class="trd-status" style="border-left:4px solid ${dCfg.bg}"><span class="trd-badge" style="color:${dCfg.color};background:${dCfg.bg}">${dCfg.label}</span></td>
				</tr>`;
			})
			.join('');

		this.$root.append(`
		<div class="trd-table-wrap">
			<table class="trd-table">${colgroup}${thead}<tbody>${tbody}</tbody></table>
		</div>`);

		const dots = Array.from({ length: totalPages }, (_, i) =>
			`<span class="trd-dot ${i === this._curPage ? 'active' : ''}" data-page="${i}"></span>`
		).join('');

		this.$root.append(`
		<div id="trd-pager">
			<button class="trd-page-btn" id="trd-prev">&#8592; Prev</button>
			<div id="trd-dots">${dots}</div>
			<span id="trd-page-label">Page ${this._curPage + 1} of ${totalPages}</span>
			<div id="trd-page-bar-wrap"><div id="trd-page-bar"></div></div>
			<button class="trd-page-btn" id="trd-next">Next &#8594;</button>
		</div>`);

		this.$root.find('.trd-dot').on('click', e => {
			this._curPage = parseInt($(e.target).data('page'));
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#trd-prev').on('click', () => {
			this._curPage = (this._curPage - 1 + totalPages) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#trd-next').on('click', () => {
			this._curPage = (this._curPage + 1) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		if (!this._paused) this._startPageTimer(totalPages);
	}

	_startPageTimer(totalPages) {
		this._stopPageTimer();
		const bar = () => document.getElementById('trd-page-bar');

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
			const bar = document.getElementById('trd-page-bar');
			if (bar) { bar.style.transition = 'none'; bar.style.width = '0%'; }
		} else {
			const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
			this._startPageTimer(totalPages);
		}
	}

	_startDataCountdown() {
		let rem = this.DATA_REFRESH;
		const el = () => document.getElementById('trd-data-num');
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
		if (document.getElementById('trd-styles')) return;
		const s = document.createElement('style');
		s.id = 'trd-styles';
		s.textContent = `
#trd-root {
	padding: 0 20px 10px;
	font-family: 'Segoe UI', system-ui, sans-serif;
}

#trd-info {
	display: flex;
	justify-content: space-between;
	font-size: 11px;
	color: #6b7280;
	margin: 0 0 4px;
}

.trd-table-wrap {
	overflow-x: auto;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
}
.trd-table {
	min-width: 1200px;
	width: 100%;
	table-layout: fixed;
	border-collapse: collapse;
	font-size: 13px;
	color: #111827;
}
.trd-table thead tr { height: 45px; }
.trd-table thead th {
	background: #f9fafb;
	padding: 4px 12px;
	text-align: left;
	font-size: 12px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.5px;
	color: #374151;
	border-bottom: 2px solid #e5e7eb;
	border-right: 1px solid #e5e7eb;
	vertical-align: middle;
	line-height: 1.2;
	box-sizing: border-box;
}
.trd-table thead th:last-child { border-right: none; }
.trd-table tbody tr { min-height: 45px; }
.trd-table tbody td {
	padding: 6px 12px;
	border-bottom: 1px solid #f3f4f6;
	border-right: 1px solid #f0f0f0;
	vertical-align: middle;
	box-sizing: border-box;
}
.trd-table tbody td:last-child { border-right: none; }
.trd-table tbody tr:last-child td { border-bottom: none; }
.trd-table tbody tr:hover td { background: #f9fafb; }

.trd-num { color: #9ca3af; width: 36px; }
.trd-wrap {
	white-space: normal;
	word-break: break-word;
	overflow-wrap: break-word;
	line-height: 1.2;
}

.trd-link {
	color: #111827;
	font-weight: 400;
	text-decoration: none;
}
.trd-link:hover { text-decoration: underline; }

.trd-status { white-space: normal !important; }
.trd-badge {
	display: inline-block;
	padding: 4px 12px;
	border-radius: 20px;
	font-weight: 700;
	letter-spacing: 0.3px;
	white-space: nowrap;
	font-size: 11px;
	text-transform: uppercase;
}

#trd-pager {
	display: flex;
	align-items: center;
	gap: 12px;
	margin-top: 10px;
	flex-wrap: wrap;
}

.trd-page-btn {
	padding: 5px 14px;
	font-size: 12px;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	background: #fff;
	cursor: pointer;
	color: #374151;
}
.trd-page-btn:hover { background: #f3f4f6; }

#trd-dots {
	display: flex;
	gap: 6px;
	align-items: center;
}
.trd-dot {
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: #d1d5db;
	cursor: pointer;
	transition: background 0.2s, transform 0.2s;
}
.trd-dot.active {
	background: #2563eb;
	transform: scale(1.35);
}
.trd-dot:hover { background: #9ca3af; }

#trd-page-label {
	font-size: 12px;
	color: #6b7280;
	white-space: nowrap;
}

#trd-page-bar-wrap {
	flex: 1;
	height: 4px;
	background: #e5e7eb;
	border-radius: 2px;
	overflow: hidden;
	min-width: 80px;
}
#trd-page-bar {
	height: 100%;
	width: 0%;
	background: #2563eb;
	border-radius: 2px;
}

.trd-empty {
	text-align: center;
	padding: 60px;
	color: #9ca3af;
	font-size: 15px;
}
		`;
		document.head.appendChild(s);
	}
}
