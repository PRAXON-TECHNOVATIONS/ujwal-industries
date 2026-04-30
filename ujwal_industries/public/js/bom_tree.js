const bom_tree_settings = frappe.treeview_settings["BOM"] || {};
const original_bom_onload = bom_tree_settings.onload;

function get_bom_child_nodes(node) {
	return node.$ul
		.children(".tree-node")
		.map((_, element) => $(element).children(".tree-link").data("node"))
		.get()
		.filter(Boolean);
}

function expand_bom_branch(tree, node) {
	if (!node || !node.expandable) {
		return Promise.resolve();
	}

	return tree.load_children(node).then(() => {
		const child_nodes = get_bom_child_nodes(node).filter((child) => child.expandable);
		return frappe.run_serially(child_nodes.map((child) => () => expand_bom_branch(tree, child)));
	});
}

frappe.treeview_settings["BOM"] = $.extend({}, bom_tree_settings, {
	show_expand_all: false,
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
	},
});
