import json
from decimal import Decimal
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import requests
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.marketplace.factory import get_marketplace_adapter
from core.models import (
    Brand,
    BrandCategory,
    Channel,
    ChannelPrice,
    Product,
    ProductCategory,
    ProductColor,
    ProductImage,
    ProductVariant,
    Stock,
)


PRODUCT = {
    "sku": "APMAX2-MHWP4",
    "name": "AirPods Max 2 USB-C Purple",
    "title": "AirPods Max 2 USB-C Purple",
    "category": "Наушники",
    "brand": "Apple",
    "brand_category": "AirPods",
    "color_name": "Purple",
    "color_hex": "#C8B5D9",
    "description": (
        "AirPods Max 2 USB-C Purple — оригинальные полноразмерные беспроводные наушники Apple. "
        "Поддерживают Active Noise Cancellation, Transparency mode, Personalized Spatial Audio "
        "with dynamic head tracking, Bluetooth 5.3 и зарядку через USB-C. До 20 часов прослушивания "
        "с включенным активным шумоподавлением. В комплекте Smart Case и кабель USB-C."
    ),
    "attributes": {
        "Тип": "Полноразмерные беспроводные наушники",
        "Производители": "Apple",
        "Модель": "AirPods Max 2",
        "Цвет": "Purple",
        "Состояние": "Новый",
        "Чип": "Apple H2 headphone chip in each ear cup",
        "Беспроводная связь": "Bluetooth 5.3",
        "Шумоподавление": "Active Noise Cancellation",
        "Режим прозрачности": "Transparency mode",
        "Пространственное аудио": "Personalized Spatial Audio with dynamic head tracking",
        "Автономность": "Up to 20 hours listening time with Active Noise Cancellation enabled",
        "Разъем": "USB-C",
        "Комплект": "AirPods Max 2, Smart Case, USB-C Charge Cable, Documentation",
        "Размеры": "168.6 x 187.3 x 83.4 mm",
        "Вес": "386.2 g",
        "Категория бренда": "AirPods",
        "omarket_width": 17,
        "omarket_height": 19,
        "omarket_length": 9,
        "omarket_weight": 0.52,
        "omarket_title": "AirPods Max 2 USB-C Purple",
    },
    "image_urls": [
        "https://www.apple.com/v/airpods-max/k/images/specs/hero_purple__skk4zesfid6y_large.jpg",
        "https://images.biggeek.ru/1/870/5fa9/28397-67purple_new%402x.jpg",
        "https://service.pcconnection.com/images/inhouse/FA53D5FE-F8E3-4B06-B7C2-53979A6C462A.jpg",
    ],
}


class Command(BaseCommand):
    help = "Загружает AirPods Max 2 USB-C Purple в TURAN / O!Market."

    def add_arguments(self, parser):
        parser.add_argument("--channel-id", type=int, help="ID канала TURAN O!Market.")
        parser.add_argument("--price", type=Decimal, default=Decimal("49000"), help="Цена в сомах.")
        parser.add_argument("--quantity", type=int, default=1, help="Остаток TURAN, если его еще нет в базе.")
        parser.add_argument("--category-id", type=int, help="category_id O!Market. Если не передан, подберется по API.")
        parser.add_argument("--category-name", default="Наушники", help="Название категории O!Market для поиска.")
        parser.add_argument("--dry-run", action="store_true", help="Создать/обновить в базе и показать payload без отправки.")
        parser.add_argument("--skip-images", action="store_true", help="Не перекачивать фото, если уже есть минимум 3.")

    def handle(self, *args, **options):
        channel = self.get_channel(options["channel_id"])
        category_id = options["category_id"] or self.resolve_category_id(channel, options["category_name"])

        with transaction.atomic():
            brand, _ = Brand.objects.get_or_create(name=PRODUCT["brand"])
            BrandCategory.objects.get_or_create(brand=brand, name=PRODUCT["brand_category"])
            ProductCategory.objects.get_or_create(name=PRODUCT["category"])
            color, _ = ProductColor.objects.get_or_create(
                name=PRODUCT["color_name"],
                defaults={"hash_code": PRODUCT["color_hex"]},
            )
            if color.hash_code != PRODUCT["color_hex"]:
                color.hash_code = PRODUCT["color_hex"]
                color.save(update_fields=["hash_code"])

            product, _ = Product.objects.update_or_create(
                name=PRODUCT["name"],
                defaults={
                    "category": PRODUCT["category"],
                    "brand_name": PRODUCT["brand"],
                    "brand_category": PRODUCT["brand_category"],
                    "description": PRODUCT["description"],
                },
            )
            product.colors.add(color)

            attrs = dict(PRODUCT["attributes"])
            attrs["omarket_category_id"] = category_id
            variant, _ = ProductVariant.objects.update_or_create(
                sku=PRODUCT["sku"],
                defaults={
                    "product": product,
                    "color": color,
                    "attributes": attrs,
                    "is_active": True,
                },
            )
            self.ensure_images(variant, color, skip_images=options["skip_images"])
            self.ensure_stock(variant, channel, options["quantity"], options["price"])
            price_obj, _ = ChannelPrice.objects.update_or_create(
                variant=variant,
                shop=channel.shop,
                channel=channel,
                defaults={
                    "price": options["price"],
                    "sync_status": ChannelPrice.SyncStatus.PENDING,
                    "last_sync_error": "",
                },
            )

        adapter = get_marketplace_adapter(channel)
        payload = adapter.build_payload(channel_price_ids=[price_obj.id])
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: товар создан/обновлен, но запрос в O!Market не отправлен."))
            return

        result = adapter.push_products(channel_price_ids=[price_obj.id])
        self.stdout.write(self.style.SUCCESS(f"Отправлено в TURAN O!Market: {result}"))

    def get_channel(self, channel_id):
        if channel_id:
            channel = Channel.objects.filter(id=channel_id, is_active=True).first()
        else:
            channel = (
                Channel.objects.filter(is_active=True, adapter_key__in=["omarket", "omarketshat"])
                .filter(name__icontains="TURAN")
                .first()
            )
            if not channel:
                channel = (
                    Channel.objects.filter(is_active=True, adapter_key__in=["omarket", "omarketshat"])
                    .filter(shop__name__icontains="TURAN")
                    .first()
                )
        if not channel:
            raise CommandError("Канал TURAN O!Market не найден. Передай --channel-id.")
        if not channel.api_url or not channel.api_token:
            raise CommandError(f"У канала {channel} не заполнены api_url/api_token.")
        return channel

    def resolve_category_id(self, channel, category_name):
        tree = self.send_omarket_json(channel, "api/mia/v1/category/tree").get("result") or []
        found = self.find_category(tree, [category_name, "Bluetooth-наушники", "Наушники"])
        if not found:
            raise CommandError("Не нашел category_id O!Market для наушников. Передай --category-id вручную.")
        return int(found["id"])

    def find_category(self, categories, candidates):
        normalized_candidates = [self.normalize(candidate) for candidate in candidates]
        for category in categories or []:
            name = self.normalize(category.get("name"))
            if name in normalized_candidates:
                return category
            found = self.find_category(category.get("sub_categories") or [], candidates)
            if found:
                return found
        for category in categories or []:
            name = self.normalize(category.get("name"))
            if any(candidate in name or name in candidate for candidate in normalized_candidates):
                return category
            found = self.find_category(category.get("sub_categories") or [], candidates)
            if found:
                return found
        return None

    def ensure_images(self, variant, color, skip_images=False):
        if skip_images and variant.images.count() >= 3:
            return
        variant.images.all().delete()
        for index, image_url in enumerate(PRODUCT["image_urls"]):
            suffix = PurePosixPath(urlparse(image_url).path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png"}:
                suffix = ".jpg"
            content = self.download_image(image_url, f"{PRODUCT['sku'].lower()}_{index}{suffix}")
            ProductImage.objects.create(
                variant=variant,
                image=content,
                color=color,
                is_primary=index == 0,
                order=index,
            )

    def ensure_stock(self, variant, channel, quantity, price):
        stock, created = Stock.objects.get_or_create(
            variant=variant,
            shop=channel.shop,
            defaults={
                "quantity": quantity,
                "in_stock": quantity > 0,
                "wholesale_price": price,
            },
        )
        if created:
            return
        if stock.quantity <= 0:
            stock.quantity = quantity
            stock.in_stock = quantity > 0
            stock.save(update_fields=["quantity", "in_stock", "updated_at"])

    def download_image(self, url, filename):
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Фото {url} недоступно: {exc}") from exc
        return ContentFile(response.content, name=filename)

    def send_omarket_json(self, channel, path):
        url = urljoin(channel.api_url.rstrip("/") + "/", path)
        request = Request(
            url,
            headers={
                "X-Access-Token": channel.api_token,
                "Accept": "application/json",
                "User-Agent": "ShopAdminOMarketImporter/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise CommandError(f"O!Market GET {url} вернул {exc.code}: {body}") from exc
        except URLError as exc:
            raise CommandError(f"O!Market GET {url} недоступен: {exc.reason}") from exc
        return json.loads(body) if body else {}

    def normalize(self, value):
        return str(value or "").strip().casefold().replace("ё", "е")
