frappe.pages['stock-requirements'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Stock / Requirements List',
		single_column: true,
	});
	new StockRequirementsList(wrapper, page);
};

// ─── Icons per MRP element type ───────────────────────────────────────────────
const ICONS = {
	po: { label: 'Purchase Order',       color: '#0369a1', bg: '#e0f2fe', border: '#38bdf8', symbol: 'PO' },
	pr: { label: 'Purchase Requisition', color: '#7c3aed', bg: '#ede9fe', border: '#a78bfa', symbol: 'PR' },
	wo: { label: 'Work Order',           color: '#065f46', bg: '#d1fae5', border: '#34d399', symbol: 'WO' },
	so: { label: 'Sales Order',          color: '#be185d', bg: '#fce7f3', border: '#f9a8d4', symbol: 'SO' },
	mr: { label: 'Material Request',     color: '#b45309', bg: '#fef3c7', border: '#fcd34d', symbol: 'MR' },
	se: { label: 'Stock Entry',          color: '#1d4ed8', bg: '#dbeafe', border: '#93c5fd', symbol: 'SE' },
};

class StockRequirementsList {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.data = null;
		this._injectStyles();
		this._buildFilterBar();
	}

	// ── Filter bar ─────────────────────────────────────────────────────────
	_buildFilterBar() {
		const content = this.wrapper.querySelector('.page-content') || this.wrapper;

		const bar = document.createElement('div');
		bar.className = 'srl-filter-bar';
		bar.innerHTML = `
			<div class="srl-filter-group">
				<label class="srl-label">Item Code</label>
				<div id="srl-item-field" class="srl-link-wrapper"></div>
			</div>
			<div class="srl-filter-group">
				<label class="srl-label">Warehouse</label>
				<div id="srl-wh-field" class="srl-link-wrapper"></div>
			</div>
			<div class="srl-filter-group srl-filter-btn-group">
				<label class="srl-label">&nbsp;</label>
				<div class="srl-btn-row">
					<button id="srl-go-btn" class="btn btn-primary srl-go-btn">
						<svg width="14" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
						Search
					</button>
					<button id="srl-clear-btn" class="btn btn-default srl-clear-btn">Clear</button>
				</div>
			</div>
		`;
		content.appendChild(bar);

		// Frappe Link fields
		this._itemField = frappe.ui.form.make_control({
			parent: bar.querySelector('#srl-item-field'),
			df: { fieldtype: 'Link', options: 'Item', fieldname: 'item_code', placeholder: 'e.g. FG-001' },
			render_input: true,
		});

		this._whField = frappe.ui.form.make_control({
			parent: bar.querySelector('#srl-wh-field'),
			df: { fieldtype: 'Link', options: 'Warehouse', fieldname: 'warehouse', placeholder: 'e.g. Stores - UI' },
			render_input: true,
		});

		bar.querySelector('#srl-go-btn').addEventListener('click', () => this._load());
		bar.querySelector('#srl-clear-btn').addEventListener('click', () => this._clear());

		// Result area
		this._resultDiv = document.createElement('div');
		this._resultDiv.id = 'srl-result';
		content.appendChild(this._resultDiv);

		// Delegated toggle for BOM tree rows
		this._resultDiv.addEventListener('click', (e) => {
			const caret = e.target.closest('[data-toggle="1"]');
			if (caret) {
				const li = caret.closest('.srl-bom-node');
				if (li) li.classList.toggle('srl-bom-collapsed');
				return;
			}

			const selectEl = e.target.closest('[data-select-item="1"]');
			if (selectEl) {
				const itemCode = selectEl.dataset.itemCode;
				const itemName = selectEl.dataset.itemName;
				this._selectBomItem(itemCode, itemName);
				return;
			}

			const backBtn = e.target.closest('[data-back-to-root="1"]');
			if (backBtn) {
				this._showRootMrp();
				return;
			}

			const pageBtn = e.target.closest('[data-page-action]');
			if (pageBtn) {
				if (pageBtn.disabled) return;
				const action = pageBtn.dataset.pageAction;
				const numPages = Math.max(1, Math.ceil((this._mrpRows || []).length / this._mrpPageSize));
				if (action === 'first') this._mrpPage = 1;
				else if (action === 'prev') this._mrpPage = Math.max(1, this._mrpPage - 1);
				else if (action === 'next') this._mrpPage = Math.min(numPages, this._mrpPage + 1);
				else if (action === 'last') this._mrpPage = numPages;
				this._renderMrpTablePage();
			}
		});

		// Delegated change for page-size selector
		this._resultDiv.addEventListener('change', (e) => {
			if (e.target.classList.contains('srl-page-size-select')) {
				this._mrpPageSize = parseInt(e.target.value, 10) || 25;
				this._mrpPage = 1;
				this._renderMrpTablePage();
			}
		});

		// Auto-load from URL params
		const params = frappe.utils.get_query_params();
		if (params.item_code) {
			this._itemField.set_value(params.item_code);
			if (params.warehouse) this._whField.set_value(params.warehouse);
			setTimeout(() => this._load(), 300);
		}
	}

	// ── Load data ──────────────────────────────────────────────────────────
	_load() {
		const item = this._itemField.get_value();
		const wh   = this._whField.get_value();
		if (!item || !wh) {
			frappe.msgprint({ title: 'Required', message: 'Please enter both Item Code and Warehouse.', indicator: 'orange' });
			return;
		}
		this._resultDiv.innerHTML = `<div class="srl-loading"><div class="srl-spinner"></div><span>Loading data…</span></div>`;

		this._rootItemCode = item;
		this._rootWarehouse = wh;
		this._mrpData = null;
		this._bomData = null;
		this._mrpLoaded = false;
		this._bomLoaded = false;
		this._activeItemCode = null;
		this._activeItemName = null;
		this._rootMrpData = null;

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.page.stock_requirements.stock_requirements.get_stock_requirements',
			args: { item_code: item, warehouse: wh },
			callback: r => {
				this._mrpData = r.message || null;
				this._rootMrpData = this._mrpData;
				this._mrpLoaded = true;
				this._renderCombined();
			},
			error: () => {
				this._mrpData = null;
				this._mrpLoaded = true;
				this._mrpError = true;
				this._renderCombined();
			},
		});

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.page.stock_requirements.stock_requirements.get_bom_tree',
			args: { item_code: item },
			callback: r => {
				this._bomData = r.message || null;
				this._bomLoaded = true;
				this._renderCombined();
			},
			error: () => {
				this._bomData = null;
				this._bomLoaded = true;
				this._bomError = true;
				this._renderCombined();
			},
		});
	}

	_renderCombined() {
		if (!this._mrpLoaded || !this._bomLoaded) {
			this._resultDiv.innerHTML = `<div class="srl-loading"><div class="srl-spinner"></div><span>Loading data…</span></div>`;
			return;
		}

		let bomHtml = '';
		if (this._bomError) {
			bomHtml = '<p class="srl-empty" style="color:#dc2626">Failed to load BOM data. Check console for details.</p>';
		} else {
			bomHtml = this._bomTreeHtml(this._bomData);
		}

		let mrpHtml = '';
		if (this._mrpError) {
			mrpHtml = '<p class="srl-empty" style="color:#dc2626">Failed to load data. Check console for details.</p>';
		} else {
			this._activeItemCode = this._mrpData ? this._mrpData.item_code : this._rootItemCode;
			this._activeItemName = this._mrpData ? this._mrpData.item_name : '';
			mrpHtml = `<div id="srl-mrp-section">${this._mrpTableHtml(this._mrpData)}</div>`;
		}

		this._resultDiv.innerHTML = bomHtml + mrpHtml;

		if (!this._mrpError && this._mrpData && this._mrpRows && this._mrpRows.length) {
			this._renderMrpTablePage();
		}

		this._updateActiveTreeHighlight();
	}

	// ── Switch the MRP table to show a clicked BOM-tree item's data ───────
	_selectBomItem(itemCode, itemName) {
		if (!itemCode || !this._rootWarehouse) return;
		if (itemCode === this._activeItemCode) return; // already showing this item

		const section = this._resultDiv.querySelector('#srl-mrp-section');
		if (section) {
			section.innerHTML = `<div class="srl-loading"><div class="srl-spinner"></div><span>Loading data for ${itemCode}…</span></div>`;
		}

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.page.stock_requirements.stock_requirements.get_stock_requirements',
			args: { item_code: itemCode, warehouse: this._rootWarehouse },
			callback: r => {
				const data = r.message || null;
				this._activeItemCode = itemCode;
				this._activeItemName = itemName || (data ? data.item_name : '');
				if (section) {
					section.innerHTML = this._mrpTableHtml(data);
					if (data && this._mrpRows && this._mrpRows.length) this._renderMrpTablePage();
				}
				this._updateActiveTreeHighlight();
			},
			error: () => {
				if (section) {
					section.innerHTML = '<p class="srl-empty" style="color:#dc2626">Failed to load data. Check console for details.</p>';
				}
			},
		});
	}

	// ── Restore the MRP table to the root FG item ──────────────────────────
	_showRootMrp() {
		if (!this._rootItemCode || this._activeItemCode === this._rootItemCode) return;

		const section = this._resultDiv.querySelector('#srl-mrp-section');
		if (section) {
			section.innerHTML = `<div class="srl-loading"><div class="srl-spinner"></div><span>Loading data…</span></div>`;
		}

		// If we still have the original root data cached, reuse it
		if (this._rootMrpData) {
			this._activeItemCode = this._rootMrpData.item_code;
			this._activeItemName = this._rootMrpData.item_name;
			if (section) {
				section.innerHTML = this._mrpTableHtml(this._rootMrpData);
				if (this._mrpRows && this._mrpRows.length) this._renderMrpTablePage();
			}
			this._updateActiveTreeHighlight();
			return;
		}

		frappe.call({
			method: 'ujwal_industries.ujwal_industries.page.stock_requirements.stock_requirements.get_stock_requirements',
			args: { item_code: this._rootItemCode, warehouse: this._rootWarehouse },
			callback: r => {
				const data = r.message || null;
				this._rootMrpData = data;
				this._activeItemCode = data ? data.item_code : this._rootItemCode;
				this._activeItemName = data ? data.item_name : '';
				if (section) {
					section.innerHTML = this._mrpTableHtml(data);
					if (data && this._mrpRows && this._mrpRows.length) this._renderMrpTablePage();
				}
				this._updateActiveTreeHighlight();
			},
			error: () => {
				if (section) {
					section.innerHTML = '<p class="srl-empty" style="color:#dc2626">Failed to load data. Check console for details.</p>';
				}
			},
		});
	}

	// ── Highlight the active item's row in the BOM tree ────────────────────
	_updateActiveTreeHighlight() {
		this._resultDiv.querySelectorAll('.srl-bom-node.srl-bom-active').forEach(el => el.classList.remove('srl-bom-active'));
		if (!this._activeItemCode) return;
		const target = this._resultDiv.querySelector(`.srl-bom-node[data-item-code="${this._activeItemCode}"]`);
		if (target) target.classList.add('srl-bom-active');
	}

	_clear() {
		this._itemField.set_value('');
		this._whField.set_value('');
		this._mrpData = null;
		this._bomData = null;
		this._mrpLoaded = false;
		this._bomLoaded = false;
		this._mrpError = false;
		this._bomError = false;
		this._mrpRows = null;
		this._mrpPage = 1;
		this._rootItemCode = null;
		this._rootWarehouse = null;
		this._activeItemCode = null;
		this._activeItemName = null;
		this._rootMrpData = null;
		this._resultDiv.innerHTML = '';
	}

	// ── Render ─────────────────────────────────────────────────────────────
	_mrpTableHtml(d) {
		if (!d) return '<p class="srl-empty">No data returned.</p>';

		const rows = d.rows || [];
		this._mrpRows  = rows;
		this._mrpUom   = d.stock_uom || '';
		this._mrpToday = frappe.datetime.get_today();
		if (!this._mrpPageSize) this._mrpPageSize = 25;
		this._mrpPage = 1;

		// ── Banner: which item's data is currently shown ────────────────────
		const isRoot = d.item_code === this._rootItemCode;
		const bannerHtml = `
			<div class="srl-active-item-banner ${isRoot ? 'srl-active-item-root' : 'srl-active-item-sub'}">
				<span class="srl-active-item-label">Showing data for:</span>
				<span class="srl-active-item-code">${d.item_code}</span>
				<span class="srl-active-item-name">${d.item_name || ''}</span>
				${!isRoot ? `<button class="btn btn-default srl-back-btn" data-back-to-root="1">← Back to ${this._rootItemCode}</button>` : ''}
			</div>
		`;

		// ── Legend ────────────────────────────────────────────────────────
		const legendHtml = `
			<div class="srl-legend">
				${Object.values(ICONS).map(ic => `
					<span class="srl-legend-item">
						<span class="srl-badge" style="background:${ic.bg};color:${ic.color};border-color:${ic.border}">${ic.symbol}</span>
						${ic.label}
					</span>`).join('')}
			</div>
		`;

		if (!rows.length) {
			return '<div class="srl-section-title">Stock / Requirements</div>' + bannerHtml + legendHtml + '<p class="srl-empty">No open MRP elements found for this item/warehouse.</p>';
		}

		return `
			<div class="srl-section-title">Stock / Requirements</div>
			${bannerHtml}
			${legendHtml}
			<div id="srl-mrp-table-area"></div>
		`;
	}

	// ── Re-render just the table body + pagination for the current page ───
	_renderMrpTablePage() {
		const area = this._resultDiv.querySelector('#srl-mrp-table-area');
		if (!area) return;

		const rows     = this._mrpRows || [];
		const uom      = this._mrpUom;
		const today    = this._mrpToday;
		const pageSize = this._mrpPageSize;
		const total    = rows.length;
		const numPages = Math.max(1, Math.ceil(total / pageSize));
		if (this._mrpPage > numPages) this._mrpPage = numPages;
		if (this._mrpPage < 1) this._mrpPage = 1;

		const startIdx = (this._mrpPage - 1) * pageSize;
		const pageRows = rows.slice(startIdx, startIdx + pageSize);

		const tableRows = pageRows.map((r) => {
			const ic        = ICONS[r.icon] || { label: r.document_type, color: '#374151', bg: '#f3f4f6', border: '#d1d5db', symbol: '??' };
			const isReq     = r.direction === 'requirement';
			const isPast    = r.date && r.date < today;
			const isToday   = r.date === today;
			const avail     = flt(r.available_qty);
			const availCls  = avail < 0 ? 'srl-avail-neg' : avail === 0 ? 'srl-avail-zero' : 'srl-avail-pos';
			const rowCls    = isPast ? 'srl-row-past' : isToday ? 'srl-row-today' : '';
			const qtySign   = isReq ? '-' : '+';
			const qtyCls    = isReq ? 'srl-qty-req' : 'srl-qty-rec';

			return `
				<tr class="srl-row ${rowCls}" data-name="${r.document_name}" data-doctype="${r.document_type}">
					<td class="srl-td srl-td-date">
						<div class="srl-date-cell">
							${isPast ? '<span class="srl-overdue-dot" title="Past due"></span>' : ''}
							${isToday ? '<span class="srl-today-dot" title="Today"></span>' : ''}
							<span>${_fmtDate(r.date)}</span>
						</div>
					</td>
					<td class="srl-td srl-td-type">
						<span class="srl-badge" style="background:${ic.bg};color:${ic.color};border-color:${ic.border}" title="${ic.label}">${ic.symbol}</span>
					</td>
					<td class="srl-td srl-td-doc">
						<a class="srl-doc-link" href="#" onclick="frappe.set_route('Form','${r.document_type}','${r.document_name}');return false;">${r.document_name}</a>
						${r.sub_type ? `<span class="srl-sub-type">${r.sub_type}</span>` : ''}
					</td>
					<td class="srl-td srl-td-party">
						${r.party ? r.party : '—'}
						${r.party_name && r.party_name !== r.party ? `<span class="srl-sub-type">${r.party_name}</span>` : ''}
					</td>
					<td class="srl-td srl-td-status">
						${r.status ? `<span class="srl-status-pill srl-status-${_statusCls(r.status)}">${r.status}</span>` : '—'}
					</td>
					<td class="srl-td srl-td-qty ${qtyCls}">
						${qtySign}${_fmtQty(Math.abs(flt(r.qty)))} ${r.uom || uom}
					</td>
					<td class="srl-td srl-td-avail">
						<span class="srl-avail ${availCls}">${_fmtQty(avail)}</span>
					</td>
				</tr>
			`;
		}).join('');

		const tableHtml = `
			<div class="srl-table-wrap">
				<table class="srl-table">
					<thead>
						<tr>
							<th class="srl-th">Date</th>
							<th class="srl-th">Type</th>
							<th class="srl-th">Document</th>
							<th class="srl-th">Party / For Item</th>
							<th class="srl-th">Status</th>
							<th class="srl-th srl-th-r">Qty</th>
							<th class="srl-th srl-th-r">Available Qty</th>
						</tr>
					</thead>
					<tbody>${tableRows}</tbody>
				</table>
			</div>
		`;

		const rangeStart = total === 0 ? 0 : startIdx + 1;
		const rangeEnd   = Math.min(startIdx + pageSize, total);

		const paginationHtml = `
			<div class="srl-pagination">
				<div class="srl-pagination-info">
					Showing ${rangeStart}–${rangeEnd} of ${total}
				</div>
				<div class="srl-pagination-controls">
					<label class="srl-page-size-label">
						Rows per page
						<select class="srl-page-size-select">
							${[10, 25, 50, 100].map(n => `<option value="${n}" ${n === pageSize ? 'selected' : ''}>${n}</option>`).join('')}
						</select>
					</label>
					<div class="srl-page-buttons">
						<button class="btn btn-default srl-page-btn" data-page-action="first" ${this._mrpPage === 1 ? 'disabled' : ''}>«</button>
						<button class="btn btn-default srl-page-btn" data-page-action="prev" ${this._mrpPage === 1 ? 'disabled' : ''}>‹</button>
						<span class="srl-page-indicator">Page ${this._mrpPage} of ${numPages}</span>
						<button class="btn btn-default srl-page-btn" data-page-action="next" ${this._mrpPage === numPages ? 'disabled' : ''}>›</button>
						<button class="btn btn-default srl-page-btn" data-page-action="last" ${this._mrpPage === numPages ? 'disabled' : ''}>»</button>
					</div>
				</div>
			</div>
		`;

		area.innerHTML = tableHtml + paginationHtml;
	}

	// ── BOM Tree HTML ────────────────────────────────────────────────────
	_bomTreeHtml(d) {
		if (!d) return '<p class="srl-empty">No data returned.</p>';

		if (!d.bom_no && (!d.children || !d.children.length)) {
			return `
				<div class="srl-section-title">BOM Tree</div>
				<p class="srl-empty">No active BOM found for this item.</p>
			`;
		}

		return `
			<div class="srl-section-title">BOM Tree</div>
			<div class="srl-bom-wrap">
				<ul class="srl-bom-tree srl-bom-root">
					${this._bomNodeHtml(d, true)}
				</ul>
			</div>
		`;
	}

	_bomNodeHtml(node, isRoot) {
		const hasChildren = node.children && node.children.length;
		const bomTag = node.bom_no
			? `<a href="#" class="srl-bom-tag" title="${node.bom_no}" onclick="event.stopPropagation();frappe.set_route('Form','BOM','${node.bom_no}');return false;">${node.bom_no}</a>`
			: '';

		const itemName = (node.item_name || '').replace(/"/g, '&quot;');

		return `
			<li class="srl-bom-node ${isRoot ? 'srl-bom-node-root' : ''}" data-item-code="${node.item_code}">
				<div class="srl-bom-row ${hasChildren ? 'srl-bom-has-children' : ''}">
					<span class="srl-bom-caret ${hasChildren ? 'srl-bom-caret-toggle' : 'srl-bom-caret-leaf'}" ${hasChildren ? 'data-toggle="1"' : ''}>${hasChildren ? '▾' : ''}</span>
					<span class="srl-bom-item-main" data-select-item="1" data-item-code="${node.item_code}" data-item-name="${itemName}" title="Click to view Stock/Requirements for this item">
						<span class="srl-bom-code">${node.item_code}</span>
						<span class="srl-bom-name">${node.item_name || ''}</span>
					</span>
					<span class="srl-bom-qty">${_fmtQty(node.qty)} ${node.uom || ''}</span>
					${bomTag}
				</div>
				${hasChildren ? `
					<ul class="srl-bom-children">
						${node.children.map(c => this._bomNodeHtml(c, false)).join('')}
					</ul>
				` : ''}
			</li>
		`;
	}

	// ── Styles ─────────────────────────────────────────────────────────────
	_injectStyles() {
		if (document.getElementById('srl-styles')) return;
		const s = document.createElement('style');
		s.id = 'srl-styles';
		s.textContent = `
/* ─── Layout ─────────────────────────────────────────────────────────── */
.srl-filter-bar {
	display: flex;
	align-items: flex-end;
	gap: 12px;
	flex-wrap: wrap;
	padding: 16px 20px 12px;
	background: var(--card-bg, #fff);
	border-bottom: 1px solid var(--border-color, #e5e7eb);
	margin-bottom: 16px;
}
.srl-filter-group { display: flex; flex-direction: column; gap: 2px; }
.srl-filter-btn-group { flex-shrink: 0; }
.srl-btn-row { display: flex; gap: 8px; height: 32px; align-items: center; }
.srl-label { font-size: 11px; font-weight: 600; color: var(--text-muted, #6b7280); text-transform: uppercase; letter-spacing: .5px; line-height: 14px; margin-bottom: 2px; }
.srl-link-wrapper { min-width: 220px; }
.srl-link-wrapper .form-group { margin-bottom: 0 !important; }
.srl-link-wrapper .control-input-wrapper,
.srl-link-wrapper .control-input { margin: 0 !important; padding: 0 !important; }
.srl-link-wrapper input {
	border-radius: 6px !important;
	height: 32px !important;
	line-height: 32px !important;
	font-size: 13px !important;
	box-sizing: border-box !important;
	margin: 0 !important;
}
.srl-go-btn { height: 30px; padding: 0 16px; font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px; border-radius: 6px; box-sizing: border-box; }
.srl-clear-btn { height: 30px; padding: 0 14px; font-size: 13px; border-radius: 6px; box-sizing: border-box; display: flex; align-items: center; }

/* ─── Legend ─────────────────────────────────────────────────────────── */
.srl-legend {
	display: flex; flex-wrap: wrap; gap: 8px;
	margin: 0 16px 10px;
	font-size: 11px; color: var(--text-muted, #6b7280);
}
.srl-legend-item { display: flex; align-items: center; gap: 4px; }

/* ─── Table ──────────────────────────────────────────────────────────── */
.srl-table-wrap {
	margin: 0 16px 12px;
	max-width: 100%;
	overflow-x: auto;
	overflow-y: visible;
	border-radius: 8px;
	border: 1px solid var(--border-color, #e5e7eb);
}
.srl-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.srl-th {
	padding: 6px 12px; background: var(--subtle-fg, #f9fafb); font-size: 11px;
	font-weight: 700; text-transform: uppercase; letter-spacing: .5px;
	color: var(--text-muted, #6b7280); border-bottom: 1px solid var(--border-color, #e5e7eb);
	white-space: nowrap;
}
.srl-th-r { text-align: right; }
.srl-td { padding: 4px 12px; border-bottom: 1px solid var(--border-color, #f3f4f6); vertical-align: middle; line-height: 1.3; }
.srl-row:last-child .srl-td { border-bottom: none; }
.srl-row:hover { background: var(--fg-hover-color, #f9fafb) !important; }
.srl-row-past  { background: #fff5f5; }
.srl-row-today { background: #fffbeb; }

.srl-td-qty, .srl-td-avail { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }

/* ─── Pagination ─────────────────────────────────────────────────────── */
.srl-pagination {
	display: flex; align-items: center; justify-content: space-between;
	flex-wrap: wrap; gap: 12px;
	margin: 0 16px 32px;
	padding: 10px 4px;
	font-size: 12px; color: var(--text-muted, #6b7280);
}
.srl-pagination-info { white-space: nowrap; }
.srl-pagination-controls { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.srl-page-size-label { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted, #6b7280); }
.srl-page-size-select {
	height: 28px; border-radius: 6px; font-size: 12px;
	border: 1px solid var(--border-color, #e5e7eb);
	background: var(--card-bg, #fff); padding: 0 6px;
}
.srl-page-buttons { display: flex; align-items: center; gap: 4px; }
.srl-page-btn {
	height: 28px; min-width: 28px; padding: 0 8px;
	font-size: 13px; border-radius: 6px; line-height: 1;
}
.srl-page-btn:disabled { opacity: .4; cursor: not-allowed; }
.srl-page-indicator { font-size: 12px; padding: 0 6px; white-space: nowrap; }

/* ─── Badges & pills ─────────────────────────────────────────────────── */
.srl-badge {
	display: inline-block; padding: 2px 7px; border-radius: 4px;
	font-size: 11px; font-weight: 700; border: 1px solid; white-space: nowrap;
}
.srl-status-pill {
	display: inline-block; padding: 2px 8px; border-radius: 20px;
	font-size: 11px; font-weight: 500; white-space: nowrap;
}
.srl-status-open    { background: #d1fae5; color: #065f46; }
.srl-status-submit  { background: #dbeafe; color: #1e40af; }
.srl-status-partial { background: #fef3c7; color: #92400e; }
.srl-status-draft   { background: #f3f4f6; color: #6b7280; }
.srl-status-default { background: #f3f4f6; color: #374151; }

/* ─── Qty colours ────────────────────────────────────────────────────── */
.srl-qty-rec { color: #065f46; }
.srl-qty-req { color: #b91c1c; }
.srl-avail { font-weight: 700; font-size: 13px; }
.srl-avail-pos  { color: #065f46; }
.srl-avail-zero { color: #6b7280; }
.srl-avail-neg  { color: #dc2626; }

/* ─── Date cell ──────────────────────────────────────────────────────── */
.srl-date-cell { display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.srl-overdue-dot { width: 7px; height: 7px; border-radius: 50%; background: #ef4444; flex-shrink: 0; }
.srl-today-dot  { width: 7px; height: 7px; border-radius: 50%; background: #f59e0b; flex-shrink: 0; }

/* ─── Doc link ───────────────────────────────────────────────────────── */
.srl-doc-link { color: var(--primary, #2563eb); font-weight: 500; text-decoration: none; }
.srl-doc-link:hover { text-decoration: underline; }
.srl-sub-type { font-size: 10px; color: var(--text-muted, #9ca3af); margin-left: 4px; }

/* ─── Misc ───────────────────────────────────────────────────────────── */
.srl-loading {
	display: flex; align-items: center; gap: 10px;
	padding: 40px 24px; color: var(--text-muted, #6b7280); font-size: 14px;
}
@keyframes srl-spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
.srl-spinner {
	width: 20px; height: 20px; border-radius: 50%;
	border: 2px solid var(--border-color, #e5e7eb);
	border-top-color: var(--primary, #2563eb);
	animation: srl-spin .7s linear infinite;
}
.srl-empty { padding: 40px 24px; color: var(--text-muted, #6b7280); font-size: 14px; }

/* ─── Active item banner ─────────────────────────────────────────────── */
.srl-active-item-banner {
	display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
	margin: 0 16px 10px;
	padding: 8px 12px;
	border-radius: 8px;
	font-size: 12px;
	border: 1px solid var(--border-color, #e5e7eb);
	background: var(--subtle-fg, #f9fafb);
}
.srl-active-item-sub {
	border-color: #a78bfa;
	background: #f5f3ff;
}
.srl-active-item-label { color: var(--text-muted, #6b7280); font-weight: 600; text-transform: uppercase; font-size: 10px; letter-spacing: .5px; }
.srl-active-item-code { font-weight: 700; color: var(--heading-color, #111827); }
.srl-active-item-name { color: var(--text-muted, #6b7280); }
.srl-back-btn {
	margin-left: auto;
	height: 26px; padding: 0 12px; font-size: 12px; border-radius: 6px;
}

/* ─── BOM item selection / active highlight ─────────────────────────── */
.srl-bom-item-main { display: flex; align-items: center; gap: 8px; flex: 1; cursor: pointer; border-radius: 4px; padding: 1px 4px; }
.srl-bom-item-main:hover .srl-bom-code,
.srl-bom-item-main:hover .srl-bom-name { color: var(--primary, #2563eb); }
.srl-bom-caret-toggle { cursor: pointer; }
.srl-bom-node.srl-bom-active > .srl-bom-row {
	background: #ede9fe;
	border-radius: 6px;
}
.srl-bom-node.srl-bom-active > .srl-bom-row .srl-bom-code,
.srl-bom-node.srl-bom-active > .srl-bom-row .srl-bom-name {
	color: #6d28d9;
}

/* ─── Section titles ─────────────────────────────────────────────────── */
.srl-section-title {
	font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: .5px;
	color: var(--text-muted, #6b7280);
	margin: 0 16px 10px;
	padding-top: 4px;
}

/* ─── BOM Tree ───────────────────────────────────────────────────────── */
.srl-bom-wrap { margin: 0 16px 32px; }
.srl-bom-tree, .srl-bom-children { list-style: none; margin: 0; padding-left: 0; }
.srl-bom-children { padding-left: 26px; }
.srl-bom-node-root > .srl-bom-row { font-weight: 700; }
.srl-bom-row {
	display: flex; align-items: center; gap: 10px;
	padding: 3px 10px; border-radius: 6px;
	font-size: 13px;
}
.srl-bom-row:hover { background: var(--fg-hover-color, #f9fafb); }
.srl-bom-has-children { cursor: pointer; }
.srl-bom-caret {
	display: inline-block; width: 14px; text-align: center;
	color: var(--text-muted, #9ca3af); font-size: 11px;
	transition: transform .15s ease; flex-shrink: 0;
}
.srl-bom-caret-leaf { visibility: hidden; }
.srl-bom-collapsed > .srl-bom-row .srl-bom-caret { transform: rotate(-90deg); }
.srl-bom-collapsed > .srl-bom-children { display: none; }
.srl-bom-code { font-weight: 700; color: var(--heading-color, #111827); white-space: nowrap; }
.srl-bom-name { color: var(--text-muted, #6b7280); flex: 1; }
.srl-bom-qty { font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.srl-bom-tag {
	font-size: 10px; font-weight: 600; color: #7c3aed;
	background: #ede9fe; border: 1px solid #a78bfa;
	padding: 1px 6px; border-radius: 4px; white-space: nowrap;
	text-decoration: none; cursor: pointer;
}
.srl-bom-tag:hover { background: #ddd6fe; text-decoration: underline; color: #6d28d9; }
		`;
		document.head.appendChild(s);
	}
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function flt(v) { return parseFloat(v) || 0; }

function _fmtDate(d) {
	if (!d || d === 'None' || d === 'null' || d === '') return '—';
	const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
	const parts = String(d).split(' ')[0].split('-');
	if (parts.length < 3) return d;
	const [y, m, day] = [parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2])];
	return isNaN(y) ? d : `${day} ${mo[m]} ${y}`;
}

function _fmtQty(v) {
	const n = flt(v);
	if (Number.isInteger(n)) return n.toLocaleString('en-IN');
	return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
}

function _statusCls(status) {
	if (!status) return 'default';
	const s = status.toLowerCase();
	if (s.includes('open') || s.includes('not started')) return 'open';
	if (s.includes('submit') || s.includes('ordered') || s.includes('to receive')) return 'submit';
	if (s.includes('partial') || s.includes('process') || s.includes('progress')) return 'partial';
	if (s.includes('draft')) return 'draft';
	return 'default';
}