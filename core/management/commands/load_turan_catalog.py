import json
import hashlib
import tempfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import requests
from PIL import Image
from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.marketplace.catalog_attributes import parse_attrs_document
from core.marketplace.factory import get_marketplace_adapter
from core.models import Channel, ChannelPrice, Product, ProductImage, ProductVariant, Stock
from core.turan_catalog import audit_catalog, fill_web_prices, identity
from core.turan_import import catalog_sku, prepare_card


class Command(BaseCommand):
    help = "Собирает WEBSITE TURAN из Excel и карточек БД; отправляет только в каналы 8 и 11."

    def add_arguments(self, parser):
        parser.add_argument("--stock", required=True)
        parser.add_argument("--prices", required=True)
        parser.add_argument("--schema", required=True)
        parser.add_argument("--sheet", default="Остатки на 04.09.2026")
        parser.add_argument("--catalog", help="JSON: исходное название Excel -> новая карточка или source_sku")
        parser.add_argument("--report", default="turan_import_report.json")
        parser.add_argument("--send", action="store_true", help="Создать карточки TURAN и отправить в оба маркета")

    def handle(self, *args, **options):
        schema = parse_attrs_document(Path(options["schema"]).read_text(encoding="utf-8"))
        audit = fill_web_prices(audit_catalog(options["stock"], options["prices"], options["sheet"]))
        overrides = json.loads(Path(options["catalog"]).read_text(encoding="utf-8")) if options["catalog"] else {}
        overrides = {identity(name): value for name, value in overrides.items()}
        channels = list(Channel.objects.filter(id__in=[8, 11], is_active=True).select_related("shop").order_by("id"))
        if len(channels) != 2 or any(
            c.shop_id != 3 or c.shop.name.upper() != "TURAN" or
            c.adapter_key != {8: "omarket", 11: "turan_bakai"}[c.id] for c in channels
        ):
            raise CommandError("Ожидались только каналы TURAN 8/omarket и 11/turan_bakai магазина 3")
        adapters = {c.id: get_marketplace_adapter(c) for c in channels}
        for adapter in adapters.values():
            adapter.validate_channel()

        variants = list(ProductVariant.objects.filter(is_active=True).select_related("product").prefetch_related("images"))
        by_name = defaultdict(list)
        by_sku = {v.sku: v for v in variants}
        for variant in variants:
            by_name[identity(variant.product.name)].append(variant)
        prepared, errors = [], []
        for row in audit["items"]:
            try:
                override = overrides.get(identity(row["name"]), {})
                source = None
                if override.get("source_sku"):
                    source = by_sku.get(override["source_sku"])
                    if source is None:
                        raise ValueError(f"Нет source_sku={override['source_sku']} в базе")
                elif not override.get("name"):
                    target = by_sku.get(catalog_sku(row["name"]))
                    matches = [target] if target else by_name.get(identity(row["name"]), [])
                    if len(matches) != 1:
                        raise ValueError("Нет единственной точной карточки в БД; нужны данные товара в --catalog")
                    source = matches[0]
                card = self.card_from_variant(source) if source else {}
                card.update({k: v for k, v in override.items() if k != "source_sku"})
                if source and source.sku != catalog_sku(row["name"]) and ChannelPrice.objects.filter(
                    variant=source, channel_id__in=[8, 11], shop_id=3,
                ).exists():
                    raise ValueError("Товар уже связан с TURAN под другим SKU; создание дубля остановлено")
                prepared.append(prepare_card(row, card, schema))
            except (ValueError, TypeError, ArithmeticError) as exc:
                errors.append({"row": row["row"], "name": row["name"], "error": str(exc)})
        report = {"summary": audit["summary"], "ready": len(prepared), "errors": errors,
                  "excluded": audit["excluded"], "cards": prepared, "batches": [], "sent": False}
        if errors:
            report["available_sources"] = [
                {"source_sku": variant.sku, **self.card_from_variant(variant)} for variant in variants
            ]
        self.save_report(options["report"], report)
        if errors:
            raise CommandError(f"Готово {len(prepared)}/{len(audit['items'])}; не хватает {len(errors)} карточек. "
                               f"Подробности: {options['report']}. БД не изменена, товары не отправлялись.")
        if not options["send"]:
            self.stdout.write(f"Готово {len(prepared)} карточек. Отчет: {options['report']}. БД не изменена.")
            return

        # Download into temporary storage before any database or marketplace writes.
        with tempfile.TemporaryDirectory(prefix="turan-import-") as staging:
            images = self.stage_images(prepared, Path(staging))
            self.persist_and_send(prepared, channels, adapters, images, report, options["report"])

    def persist_and_send(self, prepared, channels, adapters, images, report, report_path):

        # Channel row locks prevent concurrent invocations of this command.
        # All cards and payloads must be valid before any rows become visible to beat.
        with transaction.atomic():
            list(Channel.objects.select_for_update().filter(id__in=[8, 11]).order_by("id"))
            ids = {8: [], 11: []}
            for card in prepared:
                variant = self.persist_card(card, images)
                for channel in channels:
                    price, _ = ChannelPrice.objects.update_or_create(
                        variant=variant, shop_id=3, channel=channel,
                        defaults={"price": Decimal(card["price_kgs"]), "discount_amount": 0,
                                  "sync_status": ChannelPrice.SyncStatus.PENDING, "last_sync_error": ""},
                    )
                    ids[channel.id].append(price.id)
            for channel_id, price_ids in ids.items():
                for batch in self.batches(price_ids, 100 if channel_id == 8 else 1000):
                    payload = adapters[channel_id].build_payload(channel_price_ids=batch)
                    if len(payload["products"]) != len(batch):
                        raise CommandError("Адаптер пропустил часть карточек; транзакция отменена")

        for channel_id, price_ids in ids.items():
            for batch in self.batches(price_ids, 100 if channel_id == 8 else 1000):
                event = {"channel_id": channel_id, "count": len(batch), "channel_price_ids": batch}
                try:
                    response = adapters[channel_id].push_products(channel_price_ids=batch)
                    event["response"] = response
                    if isinstance(response, dict) and (response.get("success") is False or response.get("error")):
                        raise CommandError("Маркет вернул ошибку; ответ сохранен в отчете")
                    event["status"] = "request_accepted"
                except Exception as exc:
                    event.update(status="failed_or_unknown", error=str(exc))
                    ChannelPrice.objects.filter(id__in=batch, shop_id=3, channel_id=channel_id).update(
                        sync_status=ChannelPrice.SyncStatus.ERROR, last_sync_error=str(exc),
                    )
                    report["batches"].append(event)
                    self.save_report(report_path, report)
                    raise CommandError(f"Отправка остановлена: {exc}. Сначала проверь отчет, не повторяй вслепую.") from exc
                report["batches"].append(event)
                self.save_report(report_path, report)
        report["sent"] = True
        self.save_report(report_path, report)
        self.stdout.write(f"Запросы на {len(prepared)} товаров отправлены в TURAN O!Market и Bakai. "
                          f"Ответы в {report_path}; публикация может требовать обработки/модерации.")

    @staticmethod
    def stage_images(cards, directory):
        result = {}
        for url in {url for card in cards for url in card["images"]}:
            path = directory / hashlib.sha256(url.encode()).hexdigest()
            total = 0
            with requests.get(url, timeout=30, stream=True) as response, path.open("wb") as output:
                response.raise_for_status()
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > 20 * 1024 * 1024:
                        raise CommandError(f"Фото превышает 20 МБ: {url}")
                    output.write(chunk)
            with Image.open(path) as picture:
                if picture.format not in {"JPEG", "PNG"}:
                    raise CommandError(f"Нужен настоящий JPG/PNG: {url}")
                suffix = ".jpg" if picture.format == "JPEG" else ".png"
                picture.verify()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[url] = (path, f"product_images/turan/{digest}{suffix}")
        for card in cards:
            if len({result[url][1] for url in card["images"]}) != 3:
                raise CommandError(f"{card['name']}: разные ссылки содержат одинаковые фотографии")
        return result

    @staticmethod
    def batches(items, size):
        for index in range(0, len(items), size):
            yield items[index:index + size]

    @staticmethod
    def save_report(path, data):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    @staticmethod
    def card_from_variant(variant):
        base = getattr(settings, "PUBLIC_MEDIA_BASE_URL", "https://shop.kkode.site").rstrip("/")
        return {"name": variant.product.name, "brand": variant.product.brand_name,
                "category": variant.product.category, "brand_category": variant.product.brand_category,
                "description": variant.product.description, "attributes": variant.attributes,
                "images": [base + image.image.url for image in variant.images.all()[:3]],
                "source_variant_id": variant.id}

    @staticmethod
    def persist_card(card, images):
        variant = ProductVariant.objects.filter(sku=card["sku"]).select_related("product").first()
        if variant and (
            variant.attributes.get("omarket_turan_source_name") != card["source_name"] or
            Stock.objects.filter(variant=variant).exclude(shop_id=3).exists() or
            ChannelPrice.objects.filter(variant=variant).exclude(shop_id=3).exists() or
            variant.product.variants.exclude(id=variant.id).exists()
        ):
            raise CommandError(f"SKU {card['sku']} не изолирован для TURAN; изменения запрещены")
        product = variant.product if variant else Product()
        for key, value in {"name": card["name"], "category": card["category"], "brand_name": card["brand"],
                           "brand_category": card.get("brand_category", ""), "description": card["description"]}.items():
            setattr(product, key, value)
        product.save()
        attrs = {**card["attributes"], "omarket_turan_source_name": card["source_name"]}
        if variant:
            variant.attributes = attrs
            variant.is_active = True
            variant.save()
        else:
            variant = ProductVariant.objects.create(product=product, sku=card["sku"], attributes=attrs)
        paths = []
        for url in card["images"]:
            staged, destination = images[url]
            if not default_storage.exists(destination):
                with staged.open("rb") as content:
                    destination = default_storage.save(destination, File(content))
            paths.append(destination)
        existing = [image.image.name for image in variant.images.all()]
        if existing != paths:
            variant.images.all().delete()
            for index, path in enumerate(paths):
                ProductImage.objects.create(variant=variant, image=path, order=index, is_primary=index == 0)
        stock_defaults = {"quantity": card["quantity"], "in_stock": card["quantity"] > 0}
        if card["pricing"].get("selected_usd"):
            stock_defaults["wholesale_price"] = Decimal(card["pricing"]["selected_usd"]) * 88
        Stock.objects.update_or_create(variant=variant, shop_id=3, defaults=stock_defaults)
        return variant
