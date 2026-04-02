import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet, update_nsm

from erpnext.assets.doctype.asset_category.asset_category import AssetCategory


class CustomAssetCategory(AssetCategory, NestedSet):
    nsm_parent_field = "parent_asset_category"

    def validate(self):
        super().validate()
        self._validate_parent_is_group()
        self._validate_group_account_rules()

    def on_update(self):
        NestedSet.on_update(self)

    def on_trash(self):
        NestedSet.validate_if_child_exists(self)
        update_nsm(self)

    def _validate_parent_is_group(self):
        if not self.parent_asset_category:
            return

        parent_is_group = frappe.db.get_value(
            "Asset Category", self.parent_asset_category, "is_group"
        )
        if not parent_is_group:
            frappe.throw(
                _("Parent Asset Category {0} must be a group node.").format(
                    frappe.bold(self.parent_asset_category)
                )
            )

    def _validate_group_account_rules(self):
        if self.is_group:
            return

        if not self.accounts:
            frappe.throw(_("Accounts are mandatory for non-group Asset Categories."))


def on_doctype_update():
    frappe.db.add_index("Asset Category", ["lft", "rgt"])
