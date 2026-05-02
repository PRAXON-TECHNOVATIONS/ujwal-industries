# Copyright (c) 2026, Ujjwal Aggrawal and Contributors
# See license.txt

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan import (
	_build_stock_adjusted_requirement_context,
)


class TestBulkPreProductionPlan(TestCase):
	def test_rm_requirement_uses_bom_parent_when_saved_parent_link_is_stale(self):
		items = {
			"fg": [
				SimpleNamespace(
					name="fg-row",
					item_code="300185",
					planned_qty=150000,
					target_warehouse="FG-WH",
					bom_no="BOM-FG",
				)
			],
			"sfg": [
				SimpleNamespace(
					name="sfg-200147",
					fg_item_code="300185",
					production_item="200147",
					parent_item_code="300185",
					bom_level=0,
					qty=150000,
					fg_warehouse="SFG-WH",
					bom_no="BOM-200147",
				),
				SimpleNamespace(
					name="sfg-200464",
					fg_item_code="300185",
					production_item="200464",
					parent_item_code="200147",
					bom_level=1,
					qty=150000,
					fg_warehouse="Stores - UI",
					bom_no="BOM-200464",
				),
				SimpleNamespace(
					name="sfg-200146",
					fg_item_code="300185",
					production_item="200146",
					parent_item_code="stale-parent-code",
					bom_level=2,
					qty=150000,
					fg_warehouse="SHOP-WH",
					bom_no="BOM-200146",
				),
			],
			"mr": [
				SimpleNamespace(
					name="mr-100227",
					item_code="100227",
					warehouse="RM-WH",
					uom="Kg",
					item_name="1.8 x 60 CRCA coil",
				)
			],
		}

		stock_by_item_warehouse = {
			("300185", "FG-WH"): 0,
			("200147", "SFG-WH"): 0,
			("200464", "Stores - UI"): 2038147,
			("200146", "SHOP-WH"): 0,
			("100227", "RM-WH"): 0,
		}

		bom_component_map = {
			"BOM-FG": [
				{"item_code": "200147", "qty_per_unit": 1.0, "child_bom_no": "BOM-200147"},
			],
			"BOM-200147": [
				{"item_code": "200464", "qty_per_unit": 1.0, "child_bom_no": "BOM-200464"},
			],
			"BOM-200464": [
				{"item_code": "200146", "qty_per_unit": 1.0, "child_bom_no": "BOM-200146"},
			],
			"BOM-200146": [
				{"item_code": "100227", "qty_per_unit": 0.01075, "child_bom_no": ""},
			],
		}

		with (
			patch(
				"ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan._get_projected_qty_for_requirement",
				side_effect=lambda item_code, warehouse: stock_by_item_warehouse.get((item_code, warehouse), 0),
			),
			patch(
				"ujwal_industries.ujwal_industries.doctype.bulk_pre_production_plan.bulk_pre_production_plan._fetch_bom_component_map",
				return_value=bom_component_map,
			),
		):
			context = _build_stock_adjusted_requirement_context(items, {"200464": "Stores - UI"})

		self.assertEqual(context["sfg_by_row"]["sfg-200464"]["net_qty"], 0)
		self.assertEqual(context["sfg_by_row"]["sfg-200146"]["net_qty"], 0)
		self.assertEqual(len(context["mr_items"]), 1)
		self.assertEqual(context["mr_items"][0].quantity, 0)
		self.assertEqual(context["mr_items"][0].required_bom_qty, 0)
