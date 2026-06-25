frappe.pages['purchase_requisition_display'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Purchase Requisition Display',
		single_column: true,
	});

	new PurchaseRequisitionDisplay(wrapper, page);
};

function fmtDt(dt) {
	if (!dt) return '—';
	const d = new Date(dt);
	const p = n => String(n).padStart(2, '0');
	return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()}`;
}

function prLink(doctype, name) {
	if (!name) return '—';
	const route = frappe.utils.get_form_link(doctype, name);
	return `<a href="${route}" class="pr-link">${frappe.utils.escape_html(name)}</a>`;
}

function num(n) {
	return (n || 0).toLocaleString();
}

class PurchaseRequisitionDisplay {
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

		this.$root = $(`<div id="pr-root"></div>`)
			.appendTo($(this.wrapper).find('.page-content'));

		this._load();
	}

	_buildToolbar() {
		this.page.add_inner_button('Refresh Now', () => this._load());

		this.$pauseBtn = $(
			`<button class="btn btn-xs btn-default" id="pr-pause-btn" style="margin-left:8px;">⏸ Pause</button>`
		).appendTo(this.page.inner_toolbar);
		this.$pauseBtn.on('click', () => this._togglePause());

		$(`<span id="pr-data-cd" style="font-size:12px;color:#6b7280;margin-left:12px;">
			Data refresh in <b id="pr-data-num">${this.DATA_REFRESH}</b>s
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
			method: 'ujwal_industries.ujwal_industries.page.purchase_requisition_display.purchase_requisition_display.get_purchase_requisition_display_data',
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
		<div id="pr-info">
			<span>${this.rows.length} open requisition line(s) &nbsp;|&nbsp; Last updated: ${now}</span>
		</div>`);

		if (!this.rows.length) {
			this.$root.append(`<div class="pr-empty">No open purchase requisitions found</div>`);
			return;
		}

		const colgroup = `
		<colgroup>
			<col style="width:4%">
			<col style="width:12%">
			<col style="width:9%">
			<col style="width:19%">
			<col style="width:11%">
			<col style="width:9%">
			<col style="width:12%">
			<col style="width:9%">
			<col style="width:18%">
		</colgroup>`;

		const thead = `
		<thead><tr>
			<th>#</th>
			<th>Purchase Requisition</th>
			<th>PR Item No</th>
			<th>PR Item Name</th>
			<th>Planned Start Date</th>
			<th>Qty</th>
			<th>Planned Recv Date</th>
			<th>Supplier No</th>
			<th>Supplier Name</th>
		</tr></thead>`;

		const tbody = pageRows.map((w, i) => {
			const globalN = start + i + 1;
			return `
			<tr>
				<td class="pr-num">${globalN}</td>
				<td>${prLink('Material Request', w.purchase_requisition)}</td>
				<td>${prLink('Item', w.pr_item_no)}</td>
				<td class="pr-wrap">${frappe.utils.escape_html(w.pr_item_name || '—')}</td>
				<td>${fmtDt(w.planned_start_date)}</td>
				<td class="pr-qty">${num(w.qty)}</td>
				<td>${fmtDt(w.planned_received_date)}</td>
				<td>${prLink('Supplier', w.supplier_no)}</td>
				<td class="pr-wrap">${frappe.utils.escape_html(w.supplier_name || '—')}</td>
			</tr>`;
		}).join('');

		this.$root.append(`
		<div class="pr-table-wrap">
			<table class="pr-table">${colgroup}${thead}<tbody>${tbody}</tbody></table>
		</div>`);

		const dots = Array.from({ length: totalPages }, (_, i) =>
			`<span class="pr-dot ${i === this._curPage ? 'active' : ''}" data-page="${i}"></span>`
		).join('');

		this.$root.append(`
		<div id="pr-pager">
			<button class="pr-page-btn" id="pr-prev">&#8592; Prev</button>
			<div id="pr-dots">${dots}</div>
			<span id="pr-page-label">Page ${this._curPage + 1} of ${totalPages}</span>
			<div id="pr-page-bar-wrap"><div id="pr-page-bar"></div></div>
			<button class="pr-page-btn" id="pr-next">Next &#8594;</button>
		</div>`);

		this.$root.find('.pr-dot').on('click', e => {
			this._curPage = parseInt($(e.target).data('page'));
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#pr-prev').on('click', () => {
			this._curPage = (this._curPage - 1 + totalPages) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		this.$root.find('#pr-next').on('click', () => {
			this._curPage = (this._curPage + 1) % totalPages;
			this._resetPageTimer();
			this._renderPage();
		});

		if (!this._paused) this._startPageTimer(totalPages);
	}

	_startPageTimer(totalPages) {
		this._stopPageTimer();
		const bar = () => document.getElementById('pr-page-bar');

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
			const bar = document.getElementById('pr-page-bar');
			if (bar) { bar.style.transition = 'none'; bar.style.width = '0%'; }
		} else {
			const totalPages = Math.ceil(this.rows.length / this.PAGE_SIZE) || 1;
			this._startPageTimer(totalPages);
		}
	}

	_startDataCountdown() {
		let rem = this.DATA_REFRESH;
		const el = () => document.getElementById('pr-data-num');
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
		if (document.getElementById('pr-styles')) return;
		const s = document.createElement('style');
		s.id = 'pr-styles';
		s.textContent = `
#pr-root {
	padding: 0 20px 10px;
	font-family: 'Segoe UI', system-ui, sans-serif;
}

#pr-info {
	display: flex;
	justify-content: space-between;
	font-size: 11px;
	color: #6b7280;
	margin: 0 0 4px;
}

.pr-table-wrap {
	overflow-x: auto;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
}
.pr-table {
	width: 100%;
	min-width: 1100px;
	table-layout: fixed;
	border-collapse: collapse;
	font-size: 11px;
	color: #111827;
}
.pr-table thead th {
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
.pr-table thead th:last-child { border-right: none; }
.pr-table tbody tr { height: 44px; }
.pr-table tbody td {
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
.pr-table tbody td:last-child  { border-right: none; }
.pr-table tbody tr:last-child td { border-bottom: none; }
.pr-table tbody tr:hover td    { background: #f9fafb; }

.pr-num  { color: #9ca3af; }
.pr-wrap {
	white-space: normal;
	word-break: break-word;
	overflow-wrap: break-word;
	line-height: 1.25;
}
.pr-qty { font-variant-numeric: tabular-nums; white-space: nowrap; }

.pr-link {
	color: #111827;
	font-weight: 400;
	text-decoration: none;
	word-break: break-word;
}
.pr-link:hover { text-decoration: underline; }

#pr-pager {
	display: flex;
	align-items: center;
	gap: 12px;
	margin-top: 10px;
	flex-wrap: wrap;
}

.pr-page-btn {
	padding: 5px 14px;
	font-size: 12px;
	border: 1px solid #d1d5db;
	border-radius: 6px;
	background: #fff;
	cursor: pointer;
	color: #374151;
}
.pr-page-btn:hover { background: #f3f4f6; }

#pr-dots {
	display: flex;
	gap: 6px;
	align-items: center;
}
.pr-dot {
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: #d1d5db;
	cursor: pointer;
	transition: background 0.2s, transform 0.2s;
}
.pr-dot.active {
	background: #2563eb;
	transform: scale(1.35);
}
.pr-dot:hover { background: #9ca3af; }

#pr-page-label {
	font-size: 12px;
	color: #6b7280;
	white-space: nowrap;
}

#pr-page-bar-wrap {
	flex: 1;
	height: 4px;
	background: #e5e7eb;
	border-radius: 2px;
	overflow: hidden;
	min-width: 80px;
}
#pr-page-bar {
	height: 100%;
	width: 0%;
	background: #2563eb;
	border-radius: 2px;
}

.pr-empty {
	text-align: center;
	padding: 60px;
	color: #9ca3af;
	font-size: 15px;
}
		`;
		document.head.appendChild(s);
	}
}
