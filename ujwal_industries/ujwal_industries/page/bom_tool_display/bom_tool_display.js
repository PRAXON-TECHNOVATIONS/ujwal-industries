frappe.pages['bom_tool_display'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Tool Status Report',
		single_column: true,
	});

	new BomToolDisplay(wrapper, page);
};

const STATUS_CFG = {
	'Under Maintenance':    { color: '#ffffff', bg: '#b91c1c', border: '#7f1d1d' },
	'Production Completed': { color: '#3f2d00', bg: '#eab308', border: '#a16207' },
	'Ready for Production': { color: '#ffffff', bg: '#15803d', border: '#14532d' },
};

function statusCfg(s) {
	return STATUS_CFG[s] || { color: '#ffffff', bg: '#4b5563', border: '#1f2937' };
}

function btLink(doctype, name) {
	if (!name) return '—';
	const route = frappe.utils.get_form_link(doctype, name);
	return `<a href="${route}" class="bt-link">${frappe.utils.escape_html(name)}</a>`;
}

function num(n) {
	return (n || 0).toLocaleString();
}

class BomToolDisplay {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.rows = [];
		this.DATA_REFRESH = 60;

		this.filters = { item: null, tool: null, status: null };

		this._dataTimer = null;
		this._paused = false;

		this._init();
	}

	_init() {
		this._injectStyles();
		this._buildToolbar();
		this._buildFilterBar();
		this._shrinkPageHeader();

		this.$root = $(`<div id="bt-root"></div>`).appendTo($(this.wrapper).find('.page-content'));

		this._load();
	}

	_buildToolbar() {
		this.page.add_inner_button('Refresh Now', () => this._load());

		this.$pauseBtn = $(
			`<button class="btn btn-xs btn-default" id="bt-pause-btn" style="margin-left:8px;">⏸ Pause</button>`
		).appendTo(this.page.inner_toolbar);
		this.$pauseBtn.on('click', () => this._togglePause());

		$(`<span id="bt-data-cd" style="font-size:12px;color:#6b7280;margin-left:12px;">
			Data refresh in <b id="bt-data-num">${this.DATA_REFRESH}</b>s
		</span>`).appendTo(this.page.inner_toolbar);
	}

	_buildFilterBar() {
		const $bar = $(`<div id="bt-filter-bar"></div>`).appendTo($(this.wrapper).find('.page-content'));

		this._makeItemLinkFilter($bar, 'FG Item', v => {
			this.filters.item = v || null;
			this._load();
		});

		this.$toolFilter = this._makeTextFilter($bar, 'Tool', v => {
			this.filters.tool = v || null;
			this._load();
		});

		const $statusWrap = $(`<div class="bt-filter-field"></div>`).appendTo($bar);
		$(`<label>Status</label>`).appendTo($statusWrap);
		this.$statusSelect = $(`
			<select class="form-control bt-status-select">
				<option value="">All Statuses</option>
				<option value="Under Maintenance">Under Maintenance</option>
				<option value="Production Completed">Production Completed</option>
				<option value="Ready for Production">Ready for Production</option>
			</select>
		`).appendTo($statusWrap);
		this.$statusSelect.on('change', () => {
			this.filters.status = this.$statusSelect.val() || null;
			this._load();
		});
	}

	_makeTextFilter($bar, label, onChange) {
		const $wrap = $(`<div class="bt-filter-field"></div>`).appendTo($bar);
		$(`<label>${label}</label>`).appendTo($wrap);
		const $input = $(`<input type="text" class="form-control" placeholder="${label}">`).appendTo($wrap);

		$input.on('input', frappe.utils.debounce(() => onChange($input.val().trim()), 400));

		return $input;
	}

	// Item search-as-you-type by item code, item name, or Part Number
	// (Item.search_fields includes custom_part_number).
	_makeItemLinkFilter($bar, label, onChange) {
		const $wrap = $(`<div class="bt-filter-field"></div>`).appendTo($bar);
		$(`<label>${label}</label>`).appendTo($wrap);

		const control = frappe.ui.form.make_control({
			parent: $wrap.get(0),
			df: {
				fieldtype: 'Link',
				fieldname: 'fg_item',
				options: 'Item',
				placeholder: label,
				get_query: () => ({ filters: { item_code: ['like', '300%'] } }),
			},
			only_input: true,
			render_input: true,
		});
		control.refresh();
		control.$input.addClass('form-control');
		control.df.onchange = () => onChange(control.get_value());

		return control;
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
		$w.find('.page-body').css({ 'padding-top': '0', 'margin-top': '0' });
		$w.find('.layout-main, .layout-main-section, .layout-main-section-wrapper').css({
			'padding-top': '0',
			'margin-top': '0',
		});
	}

	_load() {
		this._stopDataTimer();
		frappe.call({
			method: 'ujwal_industries.ujwal_industries.page.bom_tool_display.bom_tool_display.get_bom_tool_display_data',
			args: this.filters,
			callback: r => {
				this.rows = r.message || [];
				this._render();
				this._startDataCountdown();
			},
		});
	}

	_render() {
		this.$root.empty();

		const now = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

		this.$root.append(`
		<div id="bt-info">
			<span>${this.rows.length} tool row(s) &nbsp;|&nbsp; Last updated: ${now}</span>
		</div>`);

		if (!this.rows.length) {
			this.$root.append(`<div class="bt-empty">No matching tool records found</div>`);
			return;
		}

		const thead = `
		<thead><tr>
			<th>#</th>
			<th>FG Part No</th>
			<th>Item Name</th>
			<th>Part No</th>
			<th>Operation</th>
			<th>Tool No</th>
			<th>Last Qty Produced</th>
			<th>Status</th>
		</tr></thead>`;

		const tbody = this.rows
			.map((row, i) => {
				const cfg = statusCfg(row.status);
				return `
				<tr>
					<td class="bt-num">${i + 1}</td>
					<td>${btLink('Item', row.fg_part_no)}</td>
					<td class="bt-wrap">${frappe.utils.escape_html(row.item_name || '—')}</td>
					<td>${frappe.utils.escape_html(row.part_no || '—')}</td>
					<td>${frappe.utils.escape_html(row.operation || '—')}</td>
					<td>${btLink('Asset', row.tool)}</td>
					<td class="bt-qty">${num(row.qty_produced)}</td>
					<td class="bt-status" style="border-left:4px solid ${cfg.border}">
						<span class="bt-badge" style="color:${cfg.color};background:${cfg.bg}">${frappe.utils.escape_html(row.status)}</span>
					</td>
				</tr>`;
			})
			.join('');

		this.$root.append(`
		<div class="bt-table-wrap">
			<table class="bt-table">${thead}<tbody>${tbody}</tbody></table>
		</div>`);
	}

	_togglePause() {
		this._paused = !this._paused;
		this.$pauseBtn.text(this._paused ? '▶ Resume' : '⏸ Pause');
		if (this._paused) {
			this._stopDataTimer();
		} else {
			this._startDataCountdown();
		}
	}

	_startDataCountdown() {
		if (this._paused) return;
		let rem = this.DATA_REFRESH;
		const el = () => document.getElementById('bt-data-num');
		if (el()) el().textContent = rem;
		this._dataTimer = setInterval(() => {
			rem--;
			if (el()) el().textContent = rem;
			if (rem <= 0) {
				this._stopDataTimer();
				this._load();
			}
		}, 1000);
	}

	_stopDataTimer() {
		if (this._dataTimer) clearInterval(this._dataTimer);
	}

	_injectStyles() {
		if (document.getElementById('bt-styles')) return;
		const s = document.createElement('style');
		s.id = 'bt-styles';
		s.textContent = `
#bt-root {
	padding: 0 20px 10px;
	font-family: 'Segoe UI', system-ui, sans-serif;
}

#bt-filter-bar {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	padding: 2px 20px 6px;
	position: relative;
	z-index: 20;
}
.bt-filter-field {
	display: flex;
	flex-direction: column;
	min-width: 160px;
	position: relative;
}
.bt-filter-field label {
	font-size: 11px;
	color: #6b7280;
	margin-bottom: 2px;
}
.bt-filter-field .form-control,
.bt-filter-field input.input-with-feedback {
	width: 100%;
	box-sizing: border-box;
	height: 30px;
	font-size: 13px;
}
.bt-filter-field .form-group,
.bt-filter-field .frappe-control,
.bt-filter-field .clearfix {
	margin: 0;
	padding: 0;
	border: none;
}
.bt-filter-field .control-label,
.bt-filter-field .form-group .help {
	display: none !important;
}
.bt-filter-field .awesomplete {
	width: 100%;
	display: block;
}
.bt-filter-field .awesomplete > ul {
	position: absolute;
	top: 100%;
	left: 0;
	width: max-content;
	min-width: 100%;
	max-width: 360px;
	max-height: 280px;
	overflow-y: auto;
	z-index: 30;
	margin-top: 0px;
	box-shadow: 0 4px 12px rgba(0,0,0,0.12);
	border-radius: 6px;
}

#bt-info {
	display: flex;
	justify-content: space-between;
	font-size: 11px;
	color: #6b7280;
	margin: 0 0 6px;
}

.bt-table-wrap {
	overflow-x: auto;
	border: 1px solid #e5e7eb;
	border-radius: 8px;
}
.bt-table {
	width: 100%;
	min-width: 900px;
	border-collapse: collapse;
	font-size: 12px;
	color: #111827;
}
.bt-table thead th {
	background: #f9fafb;
	padding: 8px 10px;
	text-align: left;
	font-size: 11px;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.5px;
	color: #374151;
	border-bottom: 2px solid #e5e7eb;
	border-right: 1px solid #e5e7eb;
}
.bt-table thead th:last-child { border-right: none; }
.bt-table tbody td {
	padding: 6px 10px;
	border-bottom: 1px solid #f3f4f6;
	border-right: 1px solid #f0f0f0;
	vertical-align: middle;
}
.bt-table tbody td:last-child { border-right: none; }
.bt-table tbody tr:last-child td { border-bottom: none; }
.bt-table tbody tr:hover td { background: #f9fafb; }

.bt-num { color: #9ca3af; width: 36px; }
.bt-wrap { white-space: normal; word-break: break-word; }
.bt-qty { font-variant-numeric: tabular-nums; white-space: nowrap; }

.bt-link {
	color: #111827;
	font-weight: 400;
	text-decoration: none;
}
.bt-link:hover { text-decoration: underline; }

.bt-status { white-space: normal !important; }
.bt-badge {
	display: inline-block;
	padding: 4px 12px;
	border-radius: 20px;
	font-weight: 700;
	letter-spacing: 0.3px;
	white-space: nowrap;
	font-size: 11px;
	text-transform: uppercase;
}

.bt-empty {
	text-align: center;
	padding: 60px;
	color: #9ca3af;
	font-size: 15px;
}
		`;
		document.head.appendChild(s);
	}
}
