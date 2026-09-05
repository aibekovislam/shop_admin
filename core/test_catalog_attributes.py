from unittest import TestCase

from core.marketplace.catalog_attributes import has_brand_dependencies, match_attributes, parse_attrs_document


class CatalogAttributesTests(TestCase):
    def test_selected_brand_branch_only(self):
        nodes = [{"id": 606, "label": "Бренд смартфоны", "values": [
            {"id": 2781, "value": "Apple", "attributes": [
                {"id": 2021, "label": "Модель", "values": [
                    {"id": 80331, "value": "iPhone 16 Pro Max", "attributes": [
                        {"id": 2101, "label": "Объем памяти", "values": [{"id": 10997, "value": "256 ГБ"}]}
                    ]}
                ]}
            ]},
            {"id": 2783, "value": "Xiaomi", "attributes": [
                {"id": 3000, "label": "Модель", "values": [{"id": 3001, "value": "Redmi 15"}]}
            ]}
        ]}]
        selected, missing = match_attributes(nodes, {"Производители": "Apple", "Модель": "iPhone 16 Pro Max", "Память": "256GB"})
        self.assertEqual(selected, [{"attribute_id": 606, "value_id": 2781}, {"attribute_id": 2021, "value_id": 80331}, {"attribute_id": 2101, "value_id": 10997}])
        self.assertEqual(missing, [])
        self.assertTrue(has_brand_dependencies(nodes))

    def test_no_apple_defaults_for_other_brands(self):
        selected, missing = match_attributes([
            {"id": 606, "label": "Бренд смартфоны", "values": [{"id": 2781, "value": "Apple"}]}
        ], {"Бренд": "Poco"})
        self.assertEqual(selected, [])
        self.assertEqual(len(missing), 1)

    def test_does_not_match_pro_to_pro_max_or_mix_ram_and_storage(self):
        selected, missing = match_attributes([
            {"id": 1, "label": "Модель", "values": [{"id": 11, "value": "iPhone 17 Pro Max"}]},
            {"id": 2, "label": "Объем встроенной памяти смартфоны, ГБ", "values": [{"id": 21, "value": "256"}]},
            {"id": 3, "label": "Объем оперативной памяти, ГБ", "values": [{"id": 31, "value": "8"}]},
        ], {"Модель": "iPhone 17 Pro", "Память": "256 ГБ", "Оперативная память": "8 ГБ"})
        self.assertEqual(selected, [{"attribute_id": 2, "value_id": 21}, {"attribute_id": 3, "value_id": 31}])
        self.assertEqual(len(missing), 1)

    def test_console_export_with_prefix_and_suffix(self):
        text = 'root@host:~/app# cat omarket_attrs.json\nПолучено: 22\n[{"id":606,"values":[]}]\nroot@host:~/app# '
        parsed = parse_attrs_document(text)
        self.assertEqual(parsed, {"16": [{"id": 606, "values": []}]})
        self.assertFalse(has_brand_dependencies(parsed["16"]))
