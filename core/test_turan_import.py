import copy
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import Channel, ChannelPrice, Product, ProductImage, ProductVariant, Shop, Stock
from core.turan_import import catalog_sku, prepare_card


class TuranImportTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "schema.json").write_text('{"844": []}')
        self.shat = Shop.objects.create(id=2, name="SHAT", slug="shat")
        self.turan = Shop.objects.create(id=3, name="TURAN", slug="turan")
        for pk, key in [(8, "omarket"), (11, "turan_bakai")]:
            Channel.objects.create(id=pk, shop=self.turan, name=key, channel_type="marketplace",
                                   adapter_key=key, api_url="https://example.com/", api_token="test", branch_id=257)
        product = Product.objects.create(name="Test Headphones White", category="Наушники", brand_name="Test",
                                         description="Description of the actual product and its confirmed specifications.")
        self.variant = ProductVariant.objects.create(product=product, sku="SOURCE-1", attributes={"Состояние": "Новый"})
        for index in range(3):
            ProductImage.objects.create(variant=self.variant, image=f"product_images/test-{index}.jpg")
        Stock.objects.create(variant=self.variant, shop=self.shat, quantity=17, in_stock=True, wholesale_price=100)
        self.row = {"row": 521, "name": product.name, "quantity": 2, "price_kgs": "10120", "selected_usd": "100"}
        self.audit = {"items": [self.row], "excluded": [], "summary": {"products": 1}}

    def invoke(self, send=False):
        options = {"stock": "stock.xlsx", "prices": "prices.xlsx", "schema": str(self.root / "schema.json"),
                   "report": str(self.root / "report.json"), "stdout": io.StringIO(), "send": send}
        with patch("core.management.commands.load_turan_catalog.audit_catalog", return_value=copy.deepcopy(self.audit)), \
             patch("core.management.commands.load_turan_catalog.fill_web_prices", side_effect=lambda audit: audit):
            call_command("load_turan_catalog", **options)

    def test_preview_has_no_writes_or_posts(self):
        with patch("core.marketplace.omarket.OMarketAdapter.push_products") as post:
            self.invoke()
        self.assertEqual(ProductVariant.objects.count(), 1)
        self.assertFalse(ChannelPrice.objects.exists())
        post.assert_not_called()

    def test_missing_card_aborts_entire_catalog_without_writes(self):
        self.audit["items"].append({**self.row, "name": "Missing model", "row": 522})
        with self.assertRaises(CommandError):
            self.invoke(send=True)
        self.assertEqual(ProductVariant.objects.count(), 1)
        self.assertFalse(ChannelPrice.objects.exists())
        report = json.loads((self.root / "report.json").read_text())
        self.assertEqual(report["ready"], 1)
        self.assertEqual(len(report["errors"]), 1)

    def test_wrong_shop_aborts_before_writes(self):
        Channel.objects.filter(pk=11).update(shop=self.shat)
        with self.assertRaises(CommandError):
            self.invoke(send=True)
        self.assertFalse(ChannelPrice.objects.exists())

    def test_send_isolated_from_shat_and_repeat_reuses_sku(self):
        def staged(cards, directory):
            return {url: (directory / "unused", f"product_images/imported-{index}.jpg")
                    for card in cards for index, url in enumerate(card["images"])}
        with patch("core.management.commands.load_turan_catalog.Command.stage_images", side_effect=staged), \
             patch("core.management.commands.load_turan_catalog.default_storage.exists", return_value=True), \
             patch("core.marketplace.omarket.OMarketAdapter.push_products", return_value={"success": True}) as omarket, \
             patch("core.marketplace.bakai.BakaiMarketAdapter.push_products", return_value={"success": True}) as bakai:
            self.invoke(send=True)
            self.invoke(send=True)
            self.assertEqual(ProductVariant.objects.count(), 2)
            self.assertEqual(omarket.call_count, 2)
            self.assertEqual(bakai.call_count, 2)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.attributes, {"Состояние": "Новый"})
        self.assertEqual(Stock.objects.get(shop=self.shat).quantity, 17)
        self.assertEqual(ChannelPrice.objects.filter(shop=self.shat).count(), 0)
        self.assertEqual(ChannelPrice.objects.filter(shop=self.turan).count(), 2)
        self.assertEqual(Stock.objects.get(shop=self.turan).wholesale_price, 8800)

    def test_same_identity_has_stable_sku_but_memory_changes_it(self):
        self.assertEqual(catalog_sku("POCO 12/512"), catalog_sku("poco 12 / 512"))
        self.assertNotEqual(catalog_sku("POCO 12/512"), catalog_sku("POCO 8/512"))

    def test_existing_turan_listing_is_not_duplicated(self):
        ChannelPrice.objects.create(variant=self.variant, shop=self.turan, channel_id=8, price=100)
        with self.assertRaises(CommandError):
            self.invoke(send=True)
        self.assertEqual(ProductVariant.objects.count(), 1)
        self.assertEqual(ChannelPrice.objects.count(), 1)

    def test_rejected_request_stops_before_second_market(self):
        self.variant.attributes["omarket_category_id"] = 844
        self.variant.save()
        with patch("core.management.commands.load_turan_catalog.Command.stage_images", return_value={}), \
             patch("core.management.commands.load_turan_catalog.Command.persist_card", return_value=self.variant), \
             patch("core.marketplace.omarket.OMarketAdapter.push_products", return_value={"success": False}), \
             patch("core.marketplace.bakai.BakaiMarketAdapter.push_products") as bakai:
            with self.assertRaises(CommandError):
                self.invoke(send=True)
        bakai.assert_not_called()
        self.assertEqual(ChannelPrice.objects.get(channel_id=8).sync_status, "error")
        report = json.loads((self.root / "report.json").read_text())
        self.assertFalse(report["sent"])
        self.assertEqual(report["batches"][0]["status"], "failed_or_unknown")

    def test_required_value_not_in_schema_is_rejected(self):
        from core.management.commands.load_turan_catalog import Command
        card = Command.card_from_variant(self.variant)
        schema = {"844": [{"id": 1, "name": "Состояние", "required": True,
                            "values": [{"id": 2, "value": "Б/У"}]}]}
        with self.assertRaises(ValueError):
            prepare_card(self.row, card, schema)

    def test_used_source_is_rejected(self):
        self.variant.attributes = {"Состояние": "Б/У"}
        self.variant.save()
        with self.assertRaises(CommandError):
            self.invoke(send=True)
        self.assertFalse(ChannelPrice.objects.exists())
