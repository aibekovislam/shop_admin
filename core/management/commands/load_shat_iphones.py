import json
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.marketplace.factory import get_marketplace_adapter
from core.models import (
    Brand,
    BrandCategory,
    Channel,
    ChannelPrice,
    Memory,
    Product,
    ProductCategory,
    ProductColor,
    ProductImage,
    ProductVariant,
    Stock,
)


IPHONES = [
    {
        "sku": "IP17SHAT256BLKA",
        "name": "iPhone 17 256GB Black",
        "model": "iPhone 17",
        "price": Decimal("79990.00"),
        "memory": "256GB",
        "color": ("Black", "#1d1d1f"),
        "width": 71.5,
        "height": 149.6,
        "length": 7.95,
        "weight": 0.177,
        "screen": "6.3-inch Super Retina XDR OLED, 2622x1206, 460 ppi, ProMotion 120Hz",
        "chip": "A19",
        "camera": "48MP Dual Fusion: Main + Ultra Wide, 18MP Center Stage front camera",
        "battery": "Video playback up to 30 hours",
        "image_urls": [
            "https://www.apple.com/v/iphone-17/h/images/overview/highlights/cameras/cameras__bp927f4j5vqu_large.png",
            "https://www.apple.com/v/iphone-17/h/images/overview/cameras/back-camera/hero_rear_camera__baka63bo73ma_xlarge.png",
            "https://pngimg.com/uploads/iphone17/iphone17_PNG27.png",
        ],
    },
    {
        "sku": "IP17PRO256ORNGX",
        "name": "iPhone 17 Pro 256GB Cosmic Orange",
        "model": "iPhone 17 Pro",
        "price": Decimal("109990.00"),
        "memory": "256GB",
        "color": ("Cosmic Orange", "#f77f45"),
        "width": 71.9,
        "height": 150.0,
        "length": 8.75,
        "weight": 0.206,
        "screen": "6.3-inch Super Retina XDR OLED, 2622x1206, 460 ppi, ProMotion 120Hz",
        "chip": "A19 Pro",
        "camera": "48MP Pro Fusion: Main, Ultra Wide, Telephoto, up to 8x optical-quality zoom",
        "battery": "Video playback up to 33 hours",
        "image_urls": [
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/dimensions_iphone_pro__njr21lxl7pe2_large.jpg",
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/external_connectors__6srsbgigl5ei_large.jpg",
            "https://d3m9l0v76dty0.cloudfront.net/system/photos/18235216/large/bf6df445a1d85c577a3c785659b14020.png",
        ],
    },
    {
        "sku": "IP17PMAX256BLUE",
        "name": "iPhone 17 Pro Max 256GB Deep Blue",
        "model": "iPhone 17 Pro Max",
        "price": Decimal("129990.00"),
        "memory": "256GB",
        "color": ("Deep Blue", "#1f314f"),
        "width": 78.0,
        "height": 163.4,
        "length": 8.75,
        "weight": 0.233,
        "screen": "6.9-inch Super Retina XDR OLED, 2868x1320, 460 ppi, ProMotion 120Hz",
        "chip": "A19 Pro",
        "camera": "48MP Pro Fusion: Main, Ultra Wide, Telephoto, up to 8x optical-quality zoom",
        "battery": "Video playback up to 39 hours",
        "image_urls": [
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/dimensions_iphone_pro_max__cmfii10i2owi_large.jpg",
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/external_connectors__6srsbgigl5ei_large.jpg",
            "https://www.pngmart.com/files/24/iPhone-17-Pro-Max-PNG.png",
        ],
    },
]


class Command(BaseCommand):
    help = "Создаёт три тестовых iPhone 17 для канала SHAT / O!Market и отправляет их в маркетплейс."

    def add_arguments(self, parser):
        parser.add_argument("--channel-id", type=int, help="ID канала O!Market, если adapter_key не omarketshat.")
        parser.add_argument("--adapter-key", default="omarketshat", help="Ключ адаптера канала.")
        parser.add_argument("--category-id", type=int, default=1, help="category_id для O!Market.")
        parser.add_argument("--quantity", type=int, default=3, help="Остаток для каждого SKU.")
        parser.add_argument("--price-17", type=Decimal, default=Decimal("79990.00"))
        parser.add_argument("--price-17-pro", type=Decimal, default=Decimal("109990.00"))
        parser.add_argument("--price-17-pro-max", type=Decimal, default=Decimal("129990.00"))
        parser.add_argument("--dry-run", action="store_true", help="Создать товары и показать payload без отправки.")
        parser.add_argument("--skip-images", action="store_true", help="Не скачивать фото, если они уже есть.")

    def handle(self, *args, **options):
        channel = self.get_channel(options)
        prices = [options["price_17"], options["price_17_pro"], options["price_17_pro_max"]]
        payload_ids = []

        with transaction.atomic():
            brand, _ = Brand.objects.get_or_create(name="Apple")
            brand_category, _ = BrandCategory.objects.get_or_create(brand=brand, name="iPhone")
            category, _ = ProductCategory.objects.get_or_create(name="Смартфоны")
            memory, _ = Memory.objects.get_or_create(volume="256GB")
            variants = []

            for item, price in zip(IPHONES, prices):
                item = {**item, "price": price}
                color_name, color_hex = item["color"]
                color, _ = ProductColor.objects.get_or_create(
                    name=color_name,
                    defaults={"hash_code": color_hex},
                )
                if not color.hash_code:
                    color.hash_code = color_hex
                    color.save(update_fields=["hash_code"])

                product = self.upsert_product(item, category, brand, brand_category, color, memory)
                variant = self.upsert_variant(item, product, color, memory, options["category_id"])
                variants.append(variant)
                self.upsert_stock(variant, channel.shop, options["quantity"])
                price_obj = self.upsert_price(variant, channel, price)
                payload_ids.append(price_obj.id)
                if not options["skip_images"]:
                    self.ensure_images(variant, item)

            similar_skus = [variant.sku for variant in variants]
            for variant in variants:
                variant.similar_products_sku = "\n".join(sku for sku in similar_skus if sku != variant.sku)
                variant.save(update_fields=["similar_products_sku", "attributes"])

        adapter = get_marketplace_adapter(channel)
        payload = adapter.build_payload(channel_price_ids=payload_ids)
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: товары созданы/обновлены, но запрос в O!Market не отправлен."))
            return

        result = adapter.push_products(channel_price_ids=payload_ids)
        self.stdout.write(self.style.SUCCESS(f"Отправлено в {channel}: {result}"))

    def get_channel(self, options):
        if options["channel_id"]:
            channel = Channel.objects.filter(id=options["channel_id"]).first()
        else:
            channel = Channel.objects.filter(adapter_key=options["adapter_key"], is_active=True).first()
        if not channel:
            raise CommandError("Канал не найден. Передай --channel-id или проверь adapter_key.")
        if not channel.api_url or not channel.api_token:
            raise CommandError(f"У канала {channel} не заполнены API URL/API token.")
        return channel

    def upsert_product(self, item, category, brand, brand_category, color, memory):
        description = (
            f"{item['name']} — оригинальный смартфон Apple с дисплеем {item['screen']}. "
            f"Процессор {item['chip']}, камера {item['camera']}. {item['battery']}. "
            "Подходит для ежедневной работы, фото, видео, игр и активного использования."
        )
        product = ProductVariant.objects.filter(sku=item["sku"]).select_related("product").first()
        product = product.product if product else Product.objects.filter(name=item["name"]).first()
        if product is None:
            product = Product(name=item["name"])
        product.category = category.name
        product.category_ref = category
        product.brand_name = brand.name
        product.brand_ref = brand
        product.brand_category = brand_category.name
        product.brand_category_ref = brand_category
        product.description = description[:1000]
        product.save()
        product.colors.add(color)
        product.memories.add(memory)
        return product

    def upsert_variant(self, item, product, color, memory, category_id):
        attrs = {
            "Тип": item["model"],
            "Производители": "Apple",
            "Память": item["memory"],
            "Цвет": color.name,
            "Модель": item["model"],
            "Экран": item["screen"],
            "Процессор": item["chip"],
            "Камера": item["camera"],
            "omarket_category_id": category_id,
            "omarket_width": item["width"],
            "omarket_height": item["height"],
            "omarket_length": item["length"],
            "omarket_weight": item["weight"],
            "omarket_attributes": [
                {"name": "Бренд", "value": "Apple"},
                {"name": "Модель", "value": item["model"]},
                {"name": "Память", "value": item["memory"]},
                {"name": "Цвет", "value": color.name},
                {"name": "Экран", "value": item["screen"]},
                {"name": "Процессор", "value": item["chip"]},
                {"name": "Камера", "value": item["camera"]},
            ],
        }
        variant, _ = ProductVariant.objects.update_or_create(
            sku=item["sku"],
            defaults={
                "product": product,
                "color": color,
                "memory": memory,
                "attributes": attrs,
                "is_active": True,
            },
        )
        return variant

    def upsert_stock(self, variant, shop, quantity):
        Stock.objects.update_or_create(
            variant=variant,
            shop=shop,
            defaults={"quantity": quantity, "in_stock": quantity > 0},
        )

    def upsert_price(self, variant, channel, price):
        price_obj, _ = ChannelPrice.objects.update_or_create(
            variant=variant,
            shop=channel.shop,
            channel=channel,
            defaults={
                "price": price,
                "sync_status": ChannelPrice.SyncStatus.PENDING,
                "last_sync_error": "",
            },
        )
        return price_obj

    def ensure_images(self, variant, item):
        if variant.images.count() >= 3:
            return
        variant.images.all().delete()
        for index, image_url in enumerate(item["image_urls"]):
            content = self.download_image(image_url, f"{item['sku'].lower()}_{index}{Path(image_url).suffix or '.jpg'}")
            ProductImage.objects.create(
                variant=variant,
                image=content,
                is_primary=index == 0,
                order=index,
            )

    def download_image(self, url, filename):
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as response:
            return ContentFile(response.read(), name=filename)
