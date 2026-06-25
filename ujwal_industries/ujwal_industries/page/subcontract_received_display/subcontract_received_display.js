frappe.pages['subcontract_received_display'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Subcontract Received Display',
		single_column: true,
	});

	new SubcontractReceivedDisplay(wrapper, page);
};

function fmtDt(dt) {
	if (!dt) return '—';
	const d = new Date(dt);
	const p = n => String(n).padStart(2, '0');
	return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`;
}

function scrLink(doctype, name) {
	if (!name) return '—';
	const route = frappe.utils.get_form_link(doctype, name);
	return `<a href="${route}" class="scr-link">${frappe.utils.escape_html(name)}</a>`;
}

function num(n) {
	return (n || 0).toLocaleString();
}

function delayBadge(d) {
	if (d === null || d === undefined) return '—';
	const cls = d > 0 ? 'scr-delay-late' : 'scr-delay-ok';
	return `<span class="scr-delay ${cls}">${Math.abs(d)}d</span>`;
}

class SubcontractReceivedDisplay {
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

		this.$root = $(`<div id="scr-root"></div>`)
			.appendTo($(this.wrapper).find('.page-content'));

		this._load();
	}

	_buildToolbar() {
		this.page.add_inner_button('Refresh Now', () => this._load());

		this.$pauseBtn = $(
			`<button class="btn btn-xs btn-default" id="scr-pause-btn" style="margin-left:8px;">⏸ Pause</button>`
		).appendTo(this.page.inner_toolbar);
		this.$pauseBtn.on('click', () => this._togglePause());

		$(`<span id="scr-data-cd" style="font-size:12px;color:#6b7280;margin-left:12px;">
			Data refresh in <b id="scr-data-num">${this.DATA_REFRESH}</b>s
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
			method: 'ujwal_industries.ujwal_industries.page.subcontract_received_display.subcontract_received_display.get_subcontract_received_display_data',
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
		<div id="scr-info">
			<span>${this.rows.length} FG line(s) to receive &nbsp;|&nbsp; Last updated: ${now}</span>
		</div>`);

		if (!this.rows.length) {
			this.$root.append(`<div class="scr-empty">No subcontract finished goods pending</div>`);
			return;
		}

		const colgroup = `
		<colgroup>
			<col style="width:3.5%">
			<col style="width:11%">
			<col style="width:8%">
			<col style="width:16%">
			<col style="width:10%">
			<col style="width:10%">
			<col style="width:8%">
			<col style="width:11%">
			<col style="width:5%">
			<col style="width:7.5%">
			<col style="width:15%">
		</colgroup>`;

		const thead = `
		<thead><tr>
			<th>#</th>
			<th>Purchase Order</th>
			<th>PO Item No</th>
			<th>PO Item Name</th>
			<th>Planned Recv Qty</th>
			<th>Actual Recv Qty</th>
			<th>Balance Qty</th>
			<th>Planned Recv Date</th>
			<th>Delay</th>
			<th>Supplier No</th>
			<th>Supplier Name</th>
		</tr></thead>`;

		const tbody = pageRows.map((w, i) => {
			const globalN = start + i + 1;
			return `
			<tr>
				<td class="scr-num">${globalN}</td>
				<td>${scrLink('Purchase Order', w.purchase_order)}</td>
				<td>${scrLink('Item', w.po_item_no)}</td>
				<td class="scr-wrap">${frappe.utils.escape_html(w.po_item_name || '—')}</td>
				<td class="scr-qty">${num(w.planned_received_qty)}</td>
				<td class="scr-qty">${num(w.actual_received_qty)}</td>
				<td class="scr-qty">${num(w.balance_qty)}</td>
				<td>${fmtDt(w.planned_received_date)}</td>
				<td class="scr-qty">${delayBadge(w.delay_days)}</td>
				<td>${scrLink('Supplier', w.supplier_no)}</td>
				<td class="scr-wrap">${frappe.utils.escape_html(w.supplier_name || '—')}</td>
			</tr>`;
		}).join('');

		this.$root.append(`
		<div class="scr-table-wrap">
			<table class="scr-table">${colgroup}${thead}<tbody>${tbody}</tbody></table>
		</div>`);

		const dots = Array.from({ length: totalPages }, (_, i) =>
			`<span class="scr-dot ${i === this._curPage ? 'active' : ''}" data-page="${i}"></span>`
		).join('');

		this.$root.append(`
		<div id="scr-pager">
			<button class="scr-page-btn" id="scr-prev">&#8592; Prev</button>
			<div id="scr-dots">${dots}</div>
			<span id="scr-page-label">Page ${this._curPage + 1} of ${totalPages}</span>
			<div id="scr-page-bar-wrap"><div id="scr-page-bar"></div></div>
			<button class="scr-page-btn" id="scr-next">Next &#8594;</button>
		</div>`);

		this.$root.find('.scr-dot').on('click', e => {
			this._curPage = parseInt($(e.target).data('page'));
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#scr-prev').on('click', () => {
			this._curPage = (this._curPage - 1 + totalPages) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#scr-next').on('click', () => {
			this._curPage = (this._curPage + 1) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		if (!this._paused) this._startPageTimer(totalPages);
	}

	_startPageTimer(totalPages) {
		this._stopPageTimer();
		const bar = () => document.getElementById('scr-page-bar');

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
			const bar = document.getElementById('scr-page-bar');
			if (bar) { bar.style.transition = 'none'; bar.style.width = '0%'; }
		} else {
			const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
			this._startPageTimer(totalPages);
		}
	}

	_startDataCountdown() {
		let rem = this.DATA_REFRESH;
		const el = () => document.getElementById('scr-data-num');
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
		if (document.getElementById('scr-styles')) return;
		const s = document.createElement('style');
		s.id = 'scr-styles';
		s.textContent = `
#scr-root {
	padding: 0 20px 10px;
	font-family: 'Segoe UI', system-ui, sans-serif;
}

#scr-info {
	display: flex;
	justify-content: space-between;
	font-size: 11px;
	color: #6b7280;
	margin: 0 0 4px;
}

.scr-table-wrap {
	overflow-x: auto;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
}
.scr-table {
	width: 100%;
	min-width: 1100px;
	table-layout: fixed;
	border-collapse: collapse;
	font-size: 11px;
	color: #111827;
}
.scr-table thead th {
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
.scr-table thead th:last-child { border-right: none; }
.scr-table tbody tr { height: 44px; }
.scr-table tbody td {
	height: 44px;
	max-height: 44px;
	padding: 3px 6px;
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
.scr-table tbody td:last-child  { border-right: none; }
.scr-table tbody tr:last-child td { border-bottom: none; }
.scr-table tbody tr:hover td    { background: #f9fafb; }

.scr-num  { color: #9ca3af; }
.scr-wrap {
	white-space: normal;
	word-break: break-word;
	overflow-wrap: break-word;
	line-height: 1.25;
}
.scr-qty { font-variant-numeric: tabular-nums; white-space: nowrap; }

.scr-link {
	color: #111827;
	font-weight: 400;
	text-decoration: none;
	word-break: break-word;
}
.scr-link:hover { text-decoration: underline; }

.scr-delay {
	display: inline-block;
	padding: 2px 8px;
	border-radius: 20px;
	font-weight: 600;
	font-size: 11px;
	white-space: nowrap;
}
.scr-delay-late { color: #dc2626; background: #fee2e2; }
.scr-delay-ok   { color: #16a34a; background: #dcfce7; }

#scr-pager {
	display: flex;
	align-items: center;
	gap: 12px;
	margin-top: 10px;
	flex-wrap: wrap;
}

.scr-page-btn {
	padding: 5px 14px;
	font-size: 12px;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	background: #fff;
	cursor: pointer;
	color: #374151;
}
.scr-page-btn:hover { background: #f3f4f6; }

#scr-dots {
	display: flex;
	gap: 6px;
	align-items: center;
}
.scr-dot {
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: #d1d5db;
	cursor: pointer;
	transition: background 0.2s, transform 0.2s;
}
.scr-dot.active {
	background: #2563eb;
	transform: scale(1.35);
}
.scr-dot:hover { background: #9ca3af; }

#scr-page-label {
	font-size: 12px;
	color: #6b7280;
	white-space: nowrap;
}

#scr-page-bar-wrap {
	flex: 1;
	height: 4px;
	background: #e5e7eb;
	border-radius: 2px;
	overflow: hidden;
	min-width: 80px;
}
#scr-page-bar {
	height: 100%;
	width: 0%;
	background: #2563eb;
	border-radius: 2px;
}

.scr-empty {
	text-align: center;
	padding: 60px;
	color: #9ca3af;
	font-size: 15px;
}
		`;
		document.head.appendChild(s);
	}
}
