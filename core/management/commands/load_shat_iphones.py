import json
from decimal import Decimal
from pathlib import PurePosixPath
from urllib.parse import urlencode, urljoin, urlparse
from urllib.error import HTTPError, URLError
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
        "sku": "IP17SMRT256BLK",
        "legacy_sku": "IP17SHAT256BLKA",
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
        "screen_size": "6.3",
        "os": "iOS",
        "sim": "Nano-SIM и eSIM",
        "network": "5G",
        "connector": "USB-C",
        "chip": "A19",
        "camera": "48MP Dual Fusion: Main + Ultra Wide, 18MP Center Stage front camera",
        "battery": "Video playback up to 30 hours",
        "omarket_static_filters": {
            4072: 66602,
            4079: 66618,
        },
        "image_urls": [
            "https://www.apple.com/v/iphone-17/h/images/overview/highlights/cameras/cameras__bp927f4j5vqu_large.png",
            "https://www.apple.com/v/iphone-17/h/images/overview/cameras/back-camera/hero_rear_camera__baka63bo73ma_xlarge.png",
            "https://pngimg.com/uploads/iphone17/iphone17_PNG27.png",
        ],
    },
    {
        "sku": "IP17PSM256ORG",
        "legacy_sku": "IP17PRO256ORNGX",
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
        "screen_size": "6.3",
        "os": "iOS",
        "sim": "Nano-SIM и eSIM",
        "network": "5G",
        "connector": "USB-C",
        "chip": "A19 Pro",
        "camera": "48MP Pro Fusion: Main, Ultra Wide, Telephoto, up to 8x optical-quality zoom",
        "battery": "Video playback up to 33 hours",
        "omarket_static_filters": {
            4072: 66592,
            4079: 66619,
        },
        "image_urls": [
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/dimensions_iphone_pro__njr21lxl7pe2_large.jpg",
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/external_connectors__6srsbgigl5ei_large.jpg",
            "https://d3m9l0v76dty0.cloudfront.net/system/photos/18235216/large/bf6df445a1d85c577a3c785659b14020.png",
        ],
    },
    {
        "sku": "IP17PMSM256BLU",
        "legacy_sku": "IP17PMAX256BLUE",
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
        "screen_size": "6.9",
        "os": "iOS",
        "sim": "Nano-SIM и eSIM",
        "network": "5G",
        "connector": "USB-C",
        "chip": "A19 Pro",
        "camera": "48MP Pro Fusion: Main, Ultra Wide, Telephoto, up to 8x optical-quality zoom",
        "battery": "Video playback up to 39 hours",
        "omarket_static_filters": {
            4072: 66600,
            4079: 66619,
        },
        "image_urls": [
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/dimensions_iphone_pro_max__cmfii10i2owi_large.jpg",
            "https://www.apple.com/v/iphone-17-pro/h/images/specs/external_connectors__6srsbgigl5ei_large.jpg",
            "https://www.pngmart.com/files/24/iPhone-17-Pro-Max-PNG.png",
        ],
    },
    {
        "sku": "IP16PMSM256BLK",
        "name": "iPhone 16 Pro Max 256GB Black Titanium",
        "model": "iPhone 16 Pro Max",
        "price": Decimal("119990.00"),
        "memory": "256GB",
        "color": ("Black", "#1d1d1f"),
        "width": 77.6,
        "height": 163.0,
        "length": 8.25,
        "weight": 0.227,
        "screen": "6.9-inch Super Retina XDR OLED, 2868x1320, 460 ppi, ProMotion 120Hz",
        "screen_size": "6.9",
        "os": "iOS",
        "sim": "Nano-SIM и eSIM",
        "network": "5G",
        "connector": "USB-C",
        "chip": "A18 Pro",
        "camera": "48MP Fusion Main + 48MP Ultra Wide + 12MP Telephoto, 12MP front camera",
        "battery": "Video playback up to 33 hours",
        "omarket_static_filters": {
            4072: 66602,
            4079: 66619,
            2081: 74800,
        },
        "image_urls": [
            "https://www.apple.com/v/iphone/compare/ai/images/overview/compare_iphone16_pro_max_black_titanium__etrij8y98ga6_large_2x.jpg",
            "https://www.buyitdirect.ie/Images/MYWV3QNA_2_Supersize.png",
            "https://pngate.com/wp-content/uploads/2025/03/iphone-16-pro-max-back-black-titanium-1.png",
        ],
    },
]


class Command(BaseCommand):
    help = "Создаёт три тестовых iPhone 17 для канала SHAT / O!Market и отправляет их в маркетплейс."

    def add_arguments(self, parser):
        parser.add_argument("--channel-id", type=int, help="ID канала O!Market, если adapter_key не omarketshat.")
        parser.add_argument("--adapter-key", default="omarketshat", help="Ключ адаптера канала.")
        parser.add_argument("--category-id", type=int, default=16, help="category_id для O!Market.")
        parser.add_argument(
            "--category-name",
            default="Смартфоны",
            help="Название категории O!Market, если нужно подобрать category_id через API.",
        )
        parser.add_argument("--quantity", type=int, default=3, help="Остаток для каждого SKU.")
        parser.add_argument("--price-17", type=Decimal, default=Decimal("79990.00"))
        parser.add_argument("--price-17-pro", type=Decimal, default=Decimal("109990.00"))
        parser.add_argument("--price-17-pro-max", type=Decimal, default=Decimal("129990.00"))
        parser.add_argument("--price-16-pro-max", type=Decimal, default=Decimal("119990.00"))
        parser.add_argument("--dry-run", action="store_true", help="Создать товары и показать payload без отправки.")
        parser.add_argument("--skip-images", action="store_true", help="Не скачивать фото, если они уже есть.")
        parser.add_argument(
            "--attribute-timeout",
            type=int,
            default=90,
            help="Таймаут запроса характеристик O!Market в секундах.",
        )
        parser.add_argument(
            "--keep-old-skus",
            action="store_true",
            help="Не обнулять старые SKU, которые ранее были созданы в неправильной категории.",
        )
        parser.add_argument(
            "--dump-attributes",
            action="store_true",
            help="Показать справочник характеристик O!Market для категории и выйти без создания товаров.",
        )

    def handle(self, *args, **options):
        channel = self.get_channel(options)
        category_id = options["category_id"] or self.resolve_category_id(channel, options["category_name"])
        if options["dump_attributes"]:
            attributes = self.fetch_category_attributes(channel, category_id, options["attribute_timeout"])
            self.stdout.write(json.dumps(self.serialize_attributes(attributes), ensure_ascii=False, indent=2))
            return
        filters_by_item = self.resolve_filters_by_item(channel, category_id, options["attribute_timeout"])
        prices = [
            options["price_17"],
            options["price_17_pro"],
            options["price_17_pro_max"],
            options["price_16_pro_max"],
        ]
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
                variant = self.upsert_variant(item, product, color, memory, category_id, filters_by_item[item["sku"]])
                variants.append(variant)
                self.upsert_stock(variant, channel.shop, options["quantity"])
                price_obj = self.upsert_price(variant, channel, price)
                payload_ids.append(price_obj.id)
                if not options["skip_images"]:
                    self.ensure_images(variant, item)

            if not options["keep_old_skus"]:
                payload_ids.extend(self.deactivate_legacy_skus(channel, category_id, filters_by_item))

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
        self.print_import_status(adapter, result)

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

    def upsert_variant(self, item, product, color, memory, category_id, filters):
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
            "omarket_filters": filters,
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

    def deactivate_legacy_skus(self, channel, category_id, filters_by_item):
        price_ids = []
        for item in IPHONES:
            legacy_sku = item.get("legacy_sku")
            if not legacy_sku:
                continue
            legacy_variant = ProductVariant.objects.filter(sku=legacy_sku).select_related("product").first()
            if not legacy_variant:
                continue
            legacy_attrs = dict(legacy_variant.attributes or {})
            legacy_attrs.update(
                {
                    "omarket_category_id": category_id,
                    "omarket_width": item["width"],
                    "omarket_height": item["height"],
                    "omarket_length": item["length"],
                    "omarket_weight": item["weight"],
                    "omarket_filters": filters_by_item[item["sku"]],
                }
            )
            legacy_variant.attributes = legacy_attrs
            legacy_variant.save(update_fields=["attributes"])
            self.upsert_stock(legacy_variant, channel.shop, 0)
            price_obj = self.upsert_price(legacy_variant, channel, item["price"])
            price_ids.append(price_obj.id)
        return price_ids

    def ensure_images(self, variant, item):
        existing_images = list(variant.images.all())
        has_valid_images = len(existing_images) >= 3 and all(
            urlparse(image.image.url).path.lower().endswith((".jpg", ".jpeg", ".png"))
            for image in existing_images
        )
        if has_valid_images:
            return
        variant.images.all().delete()
        for index, image_url in enumerate(item["image_urls"]):
            suffix = PurePosixPath(urlparse(image_url).path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png"}:
                suffix = ".jpg"
            content = self.download_image(image_url, f"{item['sku'].lower()}_{index}{suffix}")
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

    def print_import_status(self, adapter, result):
        task_id = (result.get("result") or {}).get("task_id") if isinstance(result, dict) else None
        if not task_id:
            return
        try:
            status = adapter.get_import_status(task_id)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Не удалось проверить task_id {task_id}: {exc}"))
            return
        self.stdout.write(self.style.SUCCESS(f"Статус task_id {task_id}:"))
        self.stdout.write(json.dumps(status, ensure_ascii=False, indent=2))

    def resolve_category_id(self, channel, category_name):
        tree = self.send_omarket_json(channel, "api/mia/v1/category/tree")
        category = self.find_category(tree.get("result", []), category_name)
        if not category:
            raise CommandError(f"Категория O!Market {category_name!r} не найдена.")
        return int(category["id"])

    def find_category(self, categories, category_name):
        normalized_name = self.normalize(category_name)
        for category in categories:
            if self.normalize(category.get("name")) == normalized_name:
                return category
            found = self.find_category(category.get("sub_categories") or [], category_name)
            if found:
                return found
        return None

    def resolve_filters_by_item(self, channel, category_id, timeout):
        attributes = self.fetch_category_attributes(channel, category_id, timeout)
        filters_by_item = {}
        for item in IPHONES:
            color_name, _ = item["color"]
            filters = self.match_filters(
                attributes,
                {
                    ("Состояние",): ["Новый"],
                    ("Гаджеты", "Тип товара", "Тип"): ["Мобильные телефоны", "Смартфоны"],
                    ("Бренд", "Производитель", "Производители"): ["Apple"],
                    ("Модель", "Линейка", "Серия"): [item["model"]],
                    ("Память", "Встроенная память", "Объем встроенной памяти", "Объём встроенной памяти", "Объем памяти", "Объём памяти"): [
                        item["memory"],
                        item["memory"].replace("GB", " GB"),
                        item["memory"].replace("GB", " ГБ"),
                        item["memory"].replace("GB", "Gb"),
                    ],
                    ("Цвет", "Цвет товара"): [color_name, *self.russian_color(color_name)],
                    ("Диагональ", "Диагональ экрана", "Размер экрана"): [
                        item["screen_size"],
                        f"{item['screen_size']} дюйм",
                        f"{item['screen_size']} дюймов",
                        f"{item['screen_size']}\"",
                    ],
                    ("Операционная система", "ОС"): [item["os"], "iOS"],
                    ("Процессор", "Чип", "Чипсет"): [item["chip"]],
                    ("Тип матрицы", "Тип экрана", "Экран", "Дисплей"): ["OLED", "Super Retina XDR", "Super Retina XDR OLED"],
                    ("Стандарт связи", "Связь", "Сеть"): [item["network"], "5G"],
                    ("SIM-карта", "Количество SIM-карт", "Тип SIM-карты"): [item["sim"], "eSIM", "Nano-SIM", "nano SIM"],
                    ("Разъем", "Разъём", "Интерфейс", "Порт зарядки"): [item["connector"], "USB Type-C"],
                },
            )
            if category_id == 16:
                filters = self.merge_missing_filters(
                    filters,
                    self.static_smartphone_filters(item),
                )
            filters_by_item[item["sku"]] = filters
        return filters_by_item

    def merge_missing_filters(self, filters, defaults):
        used_filter_ids = {item.get("filter_id") for item in filters}
        return [*filters, *[item for item in defaults if item["filter_id"] not in used_filter_ids]]

    def static_smartphone_filters(self, item):
        filters = {
            606: 2781,  # Бренд смартфоны: Apple
            4070: 66575,  # Объем встроенной памяти смартфоны: 256 ГБ
            4071: 66578,  # Поддержка 5G смартфоны: да
            2063: 10953,  # SIM-карты смартфоны: nanoSIM + eSIM
            4076: 66611,  # 4G (LTE) смартфоны: да
            2082: 10980,  # Интерфейс: USB Type-C
            4073: 66603,  # Технология NFC смартфоны: да
            2062: 10943,  # Функции и возможности смартфоны: Face ID
            2081: 66567,  # Материал корпуса смартфоны: ceramic Shield
            4074: 66608,  # Операционная система смартфоны: iOS
            4075: 66609,  # Поддержка беспроводной зарядки смартфоны: да
            4077: 66613,  # Фронтальная камера смартфоны: да
            4078: 66616,  # Слот карт памяти смартфоны: нет
            4080: 66621,  # Тип аккумулятора смартфоны: Li-ion
            677: 7051,  # Тип (смартфона): Моноблок (классический)
            1208: 8132,  # Состояние: Новый
            2041: 10913,  # Техническое состояние смартфоны: Идеальное
            **item["omarket_static_filters"],
        }
        return [{"filter_id": filter_id, "option_id": option_id} for filter_id, option_id in filters.items()]

    def fetch_category_attributes(self, channel, category_id, timeout):
        try:
            payload = self.send_omarket_json(
                channel,
                f"api/mia/v1/category/attribute?{urlencode({'category': category_id})}",
                timeout=timeout,
            )
        except (CommandError, TimeoutError) as exc:
            self.stdout.write(self.style.WARNING(f"Не удалось получить характеристики O!Market: {exc}"))
            return []
        attributes = payload.get("result") or []
        self.stdout.write(self.style.SUCCESS(f"Получено характеристик O!Market для категории {category_id}: {len(attributes)}"))
        return attributes

    def match_filters(self, attributes, desired_values):
        filters = []
        for labels, values in desired_values.items():
            attribute = self.find_attribute(attributes, labels)
            if not attribute:
                continue
            option = self.find_option(self.attribute_options(attribute), values)
            if option:
                filter_item = {"filter_id": int(self.object_id(attribute)), "option_id": int(self.object_id(option))}
                if filter_item not in filters:
                    filters.append(filter_item)
        return filters

    def find_attribute(self, attributes, labels):
        normalized_labels = {self.normalize_search(label) for label in labels}
        for attribute in attributes:
            label = attribute.get("create_label") or attribute.get("name") or attribute.get("label")
            normalized_label = self.normalize_search(label)
            if normalized_label in normalized_labels:
                return attribute
        for attribute in attributes:
            label = attribute.get("create_label") or attribute.get("name") or attribute.get("label")
            normalized_label = self.normalize_search(label)
            if any(self.safe_contains(normalized_label, expected) for expected in normalized_labels):
                return attribute
        return None

    def find_option(self, options, values):
        normalized_values = {self.normalize_search(value) for value in values}
        for option in options:
            value = option.get("value") or option.get("name") or option.get("label")
            normalized_value = self.normalize_search(value)
            if normalized_value in normalized_values:
                return option
        for option in options:
            value = option.get("value") or option.get("name") or option.get("label")
            normalized_value = self.normalize_search(value)
            if any(self.safe_contains(normalized_value, expected) for expected in normalized_values):
                return option
        return None

    def attribute_options(self, attribute):
        return attribute.get("values") or attribute.get("options") or attribute.get("filter_options") or []

    def object_id(self, item):
        return item.get("id") or item.get("filter_id") or item.get("option_id") or item.get("value_id")

    def serialize_attributes(self, attributes):
        serialized = []
        for attribute in attributes:
            serialized.append(
                {
                    "id": self.object_id(attribute),
                    "label": attribute.get("create_label") or attribute.get("name") or attribute.get("label"),
                    "values": [
                        {
                            "id": self.object_id(option),
                            "value": option.get("value") or option.get("name") or option.get("label"),
                        }
                        for option in self.attribute_options(attribute)
                    ],
                }
            )
        return serialized

    def russian_color(self, color_name):
        return {
            "Black": ["Черный", "Чёрный"],
            "Cosmic Orange": ["Оранжевый", "Космический оранжевый"],
            "Deep Blue": ["Синий", "Темно-синий", "Тёмно-синий"],
        }.get(color_name, [color_name])

    def send_omarket_json(self, channel, path, timeout=30):
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
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise CommandError(f"O!Market GET {url} вернул {exc.code}: {body}") from exc
        except URLError as exc:
            raise CommandError(f"O!Market GET {url} недоступен: {exc.reason}") from exc
        return json.loads(body) if body else {}

    def normalize(self, value):
        return str(value or "").strip().casefold().replace("ё", "е")

    def normalize_search(self, value):
        normalized = self.normalize(value)
        replacements = {
            "gb": "гб",
            "type c": "type-c",
            "usb c": "usb-c",
            "nano sim": "nano-sim",
            "‑": "-",
            "–": "-",
            "—": "-",
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        return " ".join(normalized.replace('"', "").split())

    def safe_contains(self, actual, expected):
        if len(expected) < 3:
            return actual == expected
        return expected in actual or actual in expected
