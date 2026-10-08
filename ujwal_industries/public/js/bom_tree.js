const bom_tree_settings = frappe.treeview_settings["BOM"] || {};
const original_bom_onload = bom_tree_settings.onload;
const original_bom_onrender = bom_tree_settings.onrender;
const original_bom_get_label = bom_tree_settings.get_label;

if (!document.getElementById("bom-tree-scrap-style")) {
	$("<style>", {
		id: "bom-tree-scrap-style",
		html: `
			.tree-node .tree-link.is-scrap-item .icon {
				border: 1px dotted var(--text-muted, #8d99a6);
				border-radius: 50%;
				background: transparent !important;
			}
			.tree-node .tree-link.is-scrap-item .icon svg {
				visibility: hidden;
			}
		`,
	}).appendTo("head");
}

const DEFAULT_EXPORT_LABELS = new Set([
	// BOM Item
	"BOM Item: ID", "BOM Item: Parent BOM Ref", "BOM Item: Item Code", "BOM Item: Item Name",
	"BOM Item: BOM No", "BOM Item: Qty", "BOM Item: UOM", "BOM Item: Rate",
	// Tree
	"Level", "Parent Item", "Parent BOM",
	// BOM Header
	"BOM: ID", "BOM: Item", "BOM: Item UOM", "BOM: Quantity", "BOM: Item Name",
	// BOM Operation — Parent BOM Ref required to create new operations via import
	"BOM Operation: ID", "BOM Operation: Parent BOM Ref", "BOM Operation: Row #", "BOM Operation: Sequence ID",
	"BOM Operation: Operation", "BOM Operation: Fixed Lot Capacity",
	"BOM Operation: Machine", "BOM Operation: Operation Time", "BOM Operation: BatchSize",
	// Tool Child Table
	"Tool Child Table: ID", "Tool Child Table: Parent BOM Ref", "Tool Child Table: Row #", "Tool Child Table: Operation",
	"Tool Child Table: Tool", "Tool Child Table: Tool Load Quantity", "Tool Child Table: Is Default",
	// BOM Scrap Item
	"BOM Scrap Item: ID", "BOM Scrap Item: Parent BOM Ref", "BOM Scrap Item: Row #", "BOM Scrap Item: Item Code",
	"BOM Scrap Item: Item Name", "BOM Scrap Item: Qty",
	"BOM Scrap Item: Tolerance (%)", "BOM Scrap Item: Rate",
]);

function get_bom_child_nodes(node) {
	return node.$ul
		.children(".tree-node")
		.map((_, element) => $(element).children(".tree-link").data("node"))
		.get()
		.filter(Boolean);
}

function expand_bom_branch(tree, node) {
	if (!node || !node.expandable) return Promise.resolve();
	return tree.load_children(node).then(() => {
		const children = get_bom_child_nodes(node).filter((c) => c.expandable);
		return frappe.run_serially(children.map((c) => () => expand_bom_branch(tree, c)));
	});
}

// ── BOM Selector dialog ──────────────────────────────────────────────────────

function show_bom_selector(me) {
	frappe.call({
		method: "ujwal_industries.api.bom_tree.get_top_level_boms_list",
		freeze: true,
		freeze_message: __("Loading BOMs…"),
		callback(r) {
			_render_bom_selector(r.message, me);
		},
	});
}

function _render_bom_selector(boms, me) {
	const current_selected = me.args["selected_boms"]
		? me.args["selected_boms"].split(",").map((s) => s.trim()).filter(Boolean)
		: [];

	const d = new frappe.ui.Dialog({
		title: __("Select BOMs to View / Export"),
		size: "large",
	});

	const rows_html = boms.map((b) => {
		const checked = !current_selected.length || current_selected.includes(b.bom)
			? "checked" : "";
		return `
			<div class="bom-sel-row" data-search="${b.bom.toLowerCase()} ${(b.item_code || "").toLowerCase()} ${(b.item_name || "").toLowerCase()}"
			     style="padding:5px 0; border-bottom:1px solid #f5f5f5; display:flex; align-items:center; gap:8px;">
				<input type="checkbox" class="bom-sel-chk" data-bom="${b.bom}" ${checked} style="margin:0; flex-shrink:0;">
				<span style="font-size:12px; min-width:130px; color:#5e64ff;">${b.bom}</span>
				<span style="font-size:12px; color:#333;">${b.item_code || ""}</span>
				<span style="font-size:12px; color:#888; flex:1;">${b.item_name || ""}</span>
			</div>`;
	}).join("");

	d.$body.html(`
		<div style="padding:0 4px;">
			<div style="display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; align-items:center;">
				<button class="btn btn-xs btn-default bom-sel-all">${__("Select All")}</button>
				<button class="btn btn-xs btn-default bom-sel-none">${__("Deselect All")}</button>
				<input type="text" class="form-control bom-sel-search" placeholder="${__("Search BOM / Item…")}"
				       style="max-width:240px; height:28px; font-size:12px;">
				<span class="bom-sel-count text-muted" style="font-size:12px;"></span>
			</div>
			<div style="max-height:55vh; overflow-y:auto; padding-right:4px;">
				${rows_html}
			</div>
		</div>
	`);

	function update_count() {
		const n = d.$body.find(".bom-sel-chk:checked").length;
		d.$body.find(".bom-sel-count").text(
			n === boms.length ? __("All selected") : __("{0} of {1} selected", [n, boms.length])
		);
	}
	update_count();
	d.$body.find(".bom-sel-chk").on("change", update_count);

	d.$body.find(".bom-sel-all").on("click", () => {
		d.$body.find(".bom-sel-row:visible .bom-sel-chk").prop("checked", true);
		update_count();
	});
	d.$body.find(".bom-sel-none").on("click", () => {
		d.$body.find(".bom-sel-row:visible .bom-sel-chk").prop("checked", false);
		update_count();
	});
	d.$body.find(".bom-sel-search").on("input", function () {
		const q = $(this).val().toLowerCase().trim();
		d.$body.find(".bom-sel-row").each(function () {
			$(this).toggle(!q || $(this).data("search").includes(q));
		});
	});

	d.set_primary_action(__("Apply"), () => {
		const selected = [];
		d.$body.find(".bom-sel-chk:checked").each(function () {
			selected.push($(this).data("bom"));
		});

		if (!selected.length) {
			frappe.msgprint(__("Please select at least one BOM."));
			return;
		}

		d.hide();

		// "All" selected → same as no filter
		if (selected.length === boms.length) {
			delete me.args["selected_boms"];
		} else {
			me.args["selected_boms"] = selected.join(",");
		}

		me.root_label = "BOM";
		me.make_tree();
	});

	d.set_secondary_action_label(__("Reset (Show All)"));
	d.set_secondary_action(() => {
		delete me.args["selected_boms"];
		me.root_label = "BOM";
		d.hide();
		me.make_tree();
	});

	d.show();
}

// ── Export dialog ─────────────────────────────────────────────────────────────

function show_export_dialog(selected_bom, selected_boms) {
	frappe.call({
		method: "ujwal_industries.api.bom_tree.get_all_export_fields",
		callback(r) {
			_render_export_dialog(r.message, selected_bom, selected_boms);
		},
	});
}

function _render_export_dialog(groups, selected_bom, selected_boms) {
	const d = new frappe.ui.Dialog({
		title: __("Export BOM Tree to Excel"),
		size: "extra-large",
	});

	const sections_html = groups.map((group) => {
		const fields_html = group.fields.map((f) => {
			const checked = DEFAULT_EXPORT_LABELS.has(f.label) ? "checked" : "";
			return `
				<div class="bom-col-item" data-label="${(f.label || "").toLowerCase()}" style="padding:2px 0;">
					<label style="font-weight:normal; margin:0; cursor:pointer; display:flex; align-items:center; gap:6px;">
						<input type="checkbox" class="bom-export-col" data-key="${f.fieldname}" ${checked} style="margin:0;">
						<span>${__(f.label || f.fieldname)}</span>
					</label>
				</div>`;
		}).join("");

		return `
			<div class="bom-section" style="margin-bottom:16px;">
				<div style="display:flex; align-items:center; justify-content:space-between;
				            border-bottom:1px solid #eee; padding-bottom:4px; margin-bottom:6px;">
					<span style="font-weight:600; color:#6c757d; font-size:11px; text-transform:uppercase; letter-spacing:.05em;">
						${__(group.label)}
					</span>
					<span style="font-size:11px;">
						<a class="bom-sect-select" style="cursor:pointer; color:#5e64ff;">${__("Select All")}</a>
						&nbsp;/&nbsp;
						<a class="bom-sect-unselect" style="cursor:pointer; color:#5e64ff;">${__("None")}</a>
					</span>
				</div>
				<div class="bom-field-grid" style="display:grid; grid-template-columns:repeat(3,1fr); gap:0 16px;">
					${fields_html}
				</div>
			</div>`;
	}).join("");

	const active_filter = selected_boms
		? `<span class="badge badge-pill" style="background:#e8f4ff; color:#5e64ff; font-size:12px; font-weight:normal;">
			   ${selected_boms.split(",").length} BOMs selected
		   </span>`
		: selected_bom && selected_bom !== "BOM"
			? `<span class="badge badge-pill" style="background:#e8f4ff; color:#5e64ff; font-size:12px; font-weight:normal;">
				   ${selected_bom}
			   </span>`
			: `<span class="text-muted" style="font-size:12px;">${__("All top-level BOMs")}</span>`;

	d.$body.html(`
		<div style="padding:0 4px;">
			<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px; flex-wrap:wrap; font-size:13px;">
				<strong>${__("Exporting:")}</strong> ${active_filter}
			</div>
			<div style="display:flex; align-items:center; gap:10px; margin-bottom:14px; flex-wrap:wrap;">
				<button class="btn btn-sm btn-default bom-select-all">${__("Select All")}</button>
				<button class="btn btn-sm btn-default bom-unselect-all">${__("Unselect All")}</button>
				<input type="text" class="form-control bom-search" placeholder="${__("Search fields…")}"
				       style="max-width:220px; height:30px; font-size:13px;">
			</div>
			<div class="bom-sections-wrap" style="max-height:55vh; overflow-y:auto; padding-right:4px;">
				${sections_html}
			</div>
		</div>
	`);

	d.$body.find(".bom-select-all").on("click", () =>
		d.$body.find(".bom-export-col").prop("checked", true)
	);
	d.$body.find(".bom-unselect-all").on("click", () =>
		d.$body.find(".bom-export-col").prop("checked", false)
	);
	d.$body.find(".bom-sect-select").on("click", function () {
		$(this).closest(".bom-section").find(".bom-export-col:visible").prop("checked", true);
	});
	d.$body.find(".bom-sect-unselect").on("click", function () {
		$(this).closest(".bom-section").find(".bom-export-col:visible").prop("checked", false);
	});
	d.$body.find(".bom-search").on("input", function () {
		const q = $(this).val().toLowerCase().trim();
		d.$body.find(".bom-col-item").each(function () {
			$(this).toggle(!q || $(this).data("label").includes(q));
		});
		d.$body.find(".bom-section").each(function () {
			$(this).toggle($(this).find(".bom-col-item:visible").length > 0);
		});
	});

	d.set_primary_action(__("Export"), () => {
		const selected = [];
		d.$body.find(".bom-export-col:checked").each(function () {
			selected.push($(this).data("key"));
		});
		if (!selected.length) {
			frappe.msgprint(__("Please select at least one column."));
			return;
		}
		d.hide();
		open_url_post(frappe.request.url, {
			cmd: "ujwal_industries.api.bom_tree.export_bom_tree",
			bom: selected_bom || "",
			selected_boms: selected_boms || "",
			columns: JSON.stringify(selected),
		});
	});

	d.show();
}

// ── Import dialog ─────────────────────────────────────────────────────────────

function show_import_dialog() {
	const d = new frappe.ui.Dialog({ title: __("Import BOM from Excel"), size: "extra-large" });

	d.$body.html(`
		<div style="padding:8px 4px;">
			<p style="font-size:13px; margin-bottom:6px;">
				Upload your exported BOM Excel file (with edits). The tool previews all changes before applying.
			</p>
			<div style="background:#fff8e1; border-left:3px solid #f0ad4e; padding:8px 12px; margin-bottom:8px; font-size:12px;">
				<strong>Editing existing records:</strong> Include the <strong>ID columns</strong>
				(e.g. <em>BOM Operation: ID</em>) so records can be matched.
				These are pre-ticked by default in the Export dialog.
			</div>
			<div style="background:#f0fff4; border-left:3px solid #28a745; padding:8px 12px; margin-bottom:12px; font-size:12px;">
				<strong>Adding new operations / rows:</strong> Leave the <strong>ID column blank</strong> and fill in
				<strong>Parent BOM Ref</strong> (e.g. <em>BOM Operation: Parent BOM Ref</em>) with the BOM name.
				The tool will create the new record automatically.
			</div>
			<div style="margin-bottom:14px;">
				<label style="font-size:13px; font-weight:600; display:block; margin-bottom:6px;">
					${__("Select Excel File (.xlsx)")}
				</label>
				<input type="file" class="bom-import-file" accept=".xlsx"
				       style="font-size:13px; display:block;">
			</div>
			<div class="bom-import-preview" style="display:none;">
				<div style="font-weight:600; font-size:13px; margin-bottom:8px;" class="bom-preview-title"></div>
				<div class="bom-preview-table"></div>
				<p class="bom-preview-count text-muted" style="font-size:12px; margin-top:8px;"></p>
			</div>
		</div>
	`);

	let _file_b64 = null;

	d.$body.find(".bom-import-file").on("change", function () {
		const file = this.files[0];
		if (!file) return;
		const reader = new FileReader();
		reader.onload = (e) => {
			_file_b64 = e.target.result.split(",")[1];
			d.$body.find(".bom-import-preview").hide();
			frappe.call({
				method: "ujwal_industries.api.bom_tree.preview_bom_import",
				args: { file_b64: _file_b64 },
				freeze: true,
				freeze_message: __("Analyzing changes…"),
				callback(r) {
					_render_import_preview(d, r.message.changes, r.message.warning, () => _apply_import(d, _file_b64));
				},
			});
		};
		reader.readAsDataURL(file);
	});

	d.show();
}

function _group_changes_by_bom(changes) {
	const bom_order = [];
	const by_bom = {};

	for (const c of changes) {
		const bom_key = c.bom || "";
		if (!by_bom[bom_key]) {
			bom_order.push(bom_key);
			by_bom[bom_key] = {
				bom: c.bom || "",
				bom_item: c.bom_item || "",
				bom_item_name: c.bom_item_name || "",
				records: [],
				record_map: {},
			};
		}
		const grp = by_bom[bom_key];

		if (c.change_type === "create") {
			grp.records.push({ type: "create", doctype: c.doctype, fields: c.new_fields || {} });
		} else {
			const rec_key = `${c.doctype}::${c.name}`;
			if (!grp.record_map[rec_key]) {
				const rec = { type: "update", doctype: c.doctype, name: c.name, field_changes: [] };
				grp.record_map[rec_key] = rec;
				grp.records.push(rec);
			}
			grp.record_map[rec_key].field_changes.push({ field: c.field, old: c.old, new: c.new });
		}
	}

	return bom_order.map(k => by_bom[k]);
}

function _render_import_preview(d, changes, warning, on_apply) {
	d.$body.find(".bom-import-preview").show();
	const title_el = d.$body.find(".bom-preview-title");
	const table_el = d.$body.find(".bom-preview-table");
	const count_el = d.$body.find(".bom-preview-count");

	if (warning === "no_records") {
		title_el.text(__("No Records Found"));
		table_el.html(`
			<div style="background:#fdecea; border-left:3px solid #e74c3c; padding:10px 14px; font-size:13px;">
				<strong>The ID columns were not found in your Excel.</strong><br>
				Please re-export from <em>Export to Excel</em> — the ID columns
				(<em>BOM Operation: ID</em>, <em>BOM Item: ID</em>, etc.) are now pre-ticked by default.
				Do not delete those columns before importing.
			</div>
		`);
		count_el.text("");
		d.set_primary_action(__("Close"), () => d.hide());
		return;
	}

	if (!changes || !changes.length) {
		title_el.text(__("No Changes Detected"));
		table_el.html(`<p class="text-muted" style="font-size:13px;">${__("All editable fields in the file already match the database values.")}</p>`);
		count_el.text("");
		d.set_primary_action(__("Close"), () => d.hide());
		return;
	}

	title_el.text(__("Preview of Changes"));

	const groups = _group_changes_by_bom(changes);
	let update_count = 0;
	let create_count = 0;
	let all_rows_html = "";

	for (const group of groups) {
		const bom_label = group.bom
			? `<span style="color:#1a56db; font-weight:700;">${group.bom}</span>`
			  + (group.bom_item ? ` &mdash; <span style="color:#333;">${group.bom_item}</span>` : "")
			  + (group.bom_item_name ? ` <span style="color:#888; font-size:11px;">(${group.bom_item_name})</span>` : "")
			: `<span style="color:#888;">${__("(Unknown BOM)")}</span>`;

		all_rows_html += `
			<tr style="background:#dbe9ff;">
				<td colspan="5" style="padding:6px 10px; font-size:12px; font-weight:600; border-top:2px solid #93c5fd;">
					${bom_label}
				</td>
			</tr>
		`;

		for (const rec of group.records) {
			if (rec.type === "create") {
				all_rows_html += `
					<tr style="background:#dcfce7;">
						<td colspan="5" style="font-size:12px; padding:5px 10px; padding-left:20px; font-weight:600; color:#166534;">
							<span style="background:#16a34a; color:white; font-size:10px; font-weight:700;
							             padding:1px 5px; border-radius:3px; margin-right:6px;">NEW</span>
							${rec.doctype}
						</td>
					</tr>
				`;
				for (const [fn, val] of Object.entries(rec.fields)) {
					all_rows_html += `
						<tr style="background:#f0fdf4;">
							<td style="font-size:11px; padding-left:36px; color:#888;"></td>
							<td style="font-size:11px; color:#aaa; font-style:italic;">(new)</td>
							<td style="font-size:11px; color:#555;">${fn}</td>
							<td style="font-size:11px; color:#aaa;">—</td>
							<td style="font-size:11px; color:#16a34a; font-weight:600;">${val}</td>
						</tr>
					`;
				}
				create_count++;
			} else {
				for (const fc of rec.field_changes) {
					all_rows_html += `
						<tr>
							<td style="font-size:12px; padding-left:20px;">${rec.doctype}</td>
							<td style="font-size:12px; color:#5e64ff; font-family:monospace; white-space:nowrap;">${rec.name}</td>
							<td style="font-size:12px;">${fc.field}</td>
							<td style="font-size:12px; color:#888;">${fc.old ?? ""}</td>
							<td style="font-size:12px; color:#28a745; font-weight:600;">${fc.new}</td>
						</tr>
					`;
					update_count++;
				}
			}
		}
	}

	table_el.html(`
		<div style="max-height:50vh; overflow-y:auto; border:1px solid #dee2e6; border-radius:4px;">
			<table class="table table-bordered table-condensed" style="margin:0;">
				<thead style="background:#f8f9fa; position:sticky; top:0; z-index:1;">
					<tr>
						<th style="font-size:12px; width:22%;">DocType</th>
						<th style="font-size:12px; width:20%;">Record ID</th>
						<th style="font-size:12px; width:26%;">Field</th>
						<th style="font-size:12px; width:16%;">Current Value</th>
						<th style="font-size:12px; width:16%;">New Value</th>
					</tr>
				</thead>
				<tbody>${all_rows_html}</tbody>
			</table>
		</div>
	`);

	const parts = [];
	if (update_count) parts.push(__("{0} field update(s)", [update_count]));
	if (create_count) parts.push(__("{0} new record(s)", [create_count]));
	count_el.text(parts.join(" + ") + " " + __("will be applied."));

	const apply_count = update_count + create_count;
	d.set_primary_action(__("Apply {0} Change(s)", [apply_count]), () => {
		frappe.confirm(
			__("Apply {0} change(s) directly to BOM records?", [apply_count]),
			on_apply
		);
	});
}

function _apply_import(d, file_b64) {
	frappe.call({
		method: "ujwal_industries.api.bom_tree.apply_bom_import",
		args: { file_b64 },
		freeze: true,
		freeze_message: __("Applying changes…"),
		callback(r) {
			d.hide();
			const res = r.message;
			const has_errors = res.errors && res.errors.length;
			frappe.msgprint({
				title: __("Import Complete"),
				message:
					`<strong>${__("Records updated:")}</strong> ${res.updated}<br>` +
					(res.created ? `<strong>${__("Records created:")}</strong> ${res.created}<br>` : "") +
					`<strong>${__("Rows skipped:")}</strong> ${res.skipped}<br>` +
					(has_errors
						? `<strong style="color:#e74c3c;">${__("Errors:")}</strong><br>${res.errors.join("<br>")}`
						: `<span style="color:#27ae60;">✓ ${__("No errors")}</span>`),
				indicator: has_errors ? "orange" : "green",
			});
		},
	});
}

// ── Treeview override ─────────────────────────────────────────────────────────

frappe.treeview_settings["BOM"] = $.extend({}, bom_tree_settings, {
	get_tree_nodes: "ujwal_industries.api.bom_tree.get_children",
	show_expand_all: false,
	get_label(node) {
		if (node.data.is_scrap_item) {
			const escape = frappe.utils.escape_html;
			let label = escape(node.data.item_code);
			if (node.data.item_name && node.data.item_code !== node.data.item_name) {
				label += `: ${escape(node.data.item_name)}`;
			}
			return `${label} <span class="badge badge-pill badge-light">${node.data.qty || 0} ${escape(
				__(node.data.stock_uom)
			)}</span>`;
		}
		return original_bom_get_label ? original_bom_get_label(node) : undefined;
	},
	onrender(node) {
		if (original_bom_onrender) {
			original_bom_onrender(node);
		}
		if (node.data.is_scrap_item) {
			node.$tree_link.addClass("is-scrap-item");
		}
	},
	onload(me) {
		if (original_bom_onload) {
			original_bom_onload(me);
		}

		me.page.remove_inner_button(__("Expand All"));
		me.page.remove_inner_button(__("Collapse All"));

		me.page.add_inner_button(__("Collapse All"), () => {
			me.tree.load_children(me.tree.root_node, false);
		});

		me.page.add_inner_button(__("Expand All"), () => {
			frappe.dom.freeze(__("Expanding BOM Tree"));
			expand_bom_branch(me.tree, me.tree.root_node).finally(() => {
				frappe.dom.unfreeze();
			});
		});

		me.page.add_inner_button(__("Select BOMs"), () => {
			show_bom_selector(me);
		});

		me.page.add_inner_button(__("Export to Excel"), () => {
			show_export_dialog(me.args["bom"] || "", me.args["selected_boms"] || "");
		});

		me.page.add_inner_button(__("Import from Excel"), () => {
			show_import_dialog();
		});
	},
});
