import json
import re
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image

from core.marketplace.factory import get_marketplace_adapter
from core.models import Channel, ChannelPrice, ProductVariant


ALLOWED_OMARKET_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


CATEGORY_CANDIDATES = {
    "Смартфоны": ["Смартфоны"],
    "Планшеты": ["Планшеты", "Планшетные компьютеры"],
    "Аксессуары для планшетов": ["Аксессуары для планшетов", "Аксессуары для планшетов и электронных книг"],
    "Наушники": ["Наушники", "Bluetooth-наушники"],
    "Смарт-часы": ["Смарт-часы", "Умные часы"],
    "Фитнес-трекеры": ["Фитнес-браслеты", "Фитнес-трекеры"],
    "Спортивные аксессуары": ["Спортивные аксессуары", "Аксессуары для спорта"],
    "Умные весы": ["Напольные весы", "Умные весы", "Весы"],
    "Велоаксессуары": ["Велоаксессуары", "Аксессуары для велосипеда"],
    "Автоэлектроника": ["Видеорегистраторы", "Автоэлектроника"],
    "Поисковые метки": ["Поисковые метки", "Трекеры", "Метки", "GPS-трекеры", "Аксессуары"],
    "Аксессуары": ["Аксессуары", "Аксессуары для телефонов", "Кабели и адаптеры", "Зарядные устройства"],
    "Ноутбуки": ["Ноутбуки", "Ноутбуки и ультрабуки"],
    "Компьютеры": ["Настольные компьютеры", "Компьютеры", "Моноблоки", "Мини-ПК"],
    "Умные колонки": ["Умные колонки", "Портативная акустика", "Колонки", "Акустика"],
    "Очистители воздуха": ["Очистители воздуха", "Климатическая техника", "Очистители и увлажнители воздуха"],
}


STATIC_SMARTPHONE_ATTRIBUTES = {
    606: 2781,  # Бренд смартфоны: Apple
    4071: 66578,  # Поддержка 5G смартфоны: да
    2063: 10953,  # SIM-карты смартфоны: nanoSIM + eSIM
    4076: 66611,  # 4G (LTE) смартфоны: да
    2082: 10980,  # Интерфейс: USB Type-C
    4073: 66603,  # Технология NFC смартфоны: да
    2062: 10943,  # Функции и возможности смартфоны: Face ID
    4074: 66608,  # Операционная система смартфоны: iOS
    4075: 66609,  # Поддержка беспроводной зарядки смартфоны: да
    4077: 66613,  # Фронтальная камера смартфоны: да
    4078: 66616,  # Слот карт памяти смартфоны: нет
    4080: 66621,  # Тип аккумулятора смартфоны: Li-ion
    677: 7051,  # Тип смартфона: Моноблок
    1208: 8132,  # Состояние: Новый
    2041: 10913,  # Техническое состояние смартфоны: Идеальное
}


COLOR_VALUES = {
    "black": ["Black", "Черный", "Чёрный"],
    "white": ["White", "Белый"],
    "silver": ["Silver", "Серебристый", "Серебро"],
    "gray": ["Gray", "Grey", "Серый"],
    "grey": ["Gray", "Grey", "Серый"],
    "blue": ["Blue", "Синий", "Голубой"],
    "green": ["Green", "Зеленый", "Зелёный"],
    "pink": ["Pink", "Розовый"],
    "purple": ["Purple", "Фиолетовый"],
    "orange": ["Orange", "Оранжевый"],
    "gold": ["Gold", "Золотой"],
    "titanium": ["Titanium", "Титан"],
    "midnight": ["Midnight", "Черный", "Чёрный"],
    "starlight": ["Starlight", "Бежевый", "Белый"],
}


class Command(BaseCommand):
    help = "Переносит уже загруженные SHAT товары из M-Market в O!Market."

    def add_arguments(self, parser):
        parser.add_argument("--source-adapter-key", default="mmarket", help="Канал-источник с уже загруженными товарами.")
        parser.add_argument("--target-adapter-key", default="omarketshat", help="Канал O!Market для SHAT.")
        parser.add_argument("--source-channel-id", type=int, help="ID M-Market канала, если adapter_key не подходит.")
        parser.add_argument("--target-channel-id", type=int, help="ID O!Market канала.")
        parser.add_argument("--attrs-file", default="omarket_attrs.json", help="Локальный файл с кешем attrs O!Market.")
        parser.add_argument("--batch-size", type=int, default=100, help="Размер батча импорта O!Market.")
        parser.add_argument("--dry-run", action="store_true", help="Подготовить payload без отправки в O!Market.")
        parser.add_argument("--only-category", action="append", default=[], help="Ограничить CRM-категорию, можно несколько раз.")
        parser.add_argument("--allow-fetch-attrs", action="store_true", default=True, help="Догружать attrs из API O!Market.")
        parser.add_argument("--no-fetch-attrs", action="store_false", dest="allow_fetch_attrs", help="Не дергать API attrs.")

    def handle(self, *args, **options):
        source_channel = self.get_channel(options["source_channel_id"], options["source_adapter_key"], require_branch=True)
        target_channel = self.get_channel(options["target_channel_id"], options["target_adapter_key"], require_branch=False)
        if source_channel.shop_id != target_channel.shop_id:
            raise CommandError("Канал M-Market и O!Market должны быть у одного магазина.")

        attrs_cache = self.load_attrs_cache(options["attrs_file"])
        category_tree = self.fetch_category_tree(target_channel) if options["allow_fetch_attrs"] else []
        category_ids = self.resolve_category_ids(target_channel, category_tree)
        source_prices = self.source_prices(source_channel, options["only_category"])

        prepared = []
        skipped = []
        with transaction.atomic():
            for source_price in source_prices:
                variant = source_price.variant
                skip_reason = self.skip_reason(variant, source_channel.shop)
                if skip_reason:
                    skipped.append((variant.sku, skip_reason))
                    continue
                category_name = variant.product.category
                category_id = category_ids.get(category_name)
                if not category_id:
                    skipped.append((variant.sku, f"не найден O!Market category_id для CRM-категории {category_name!r}"))
                    continue
                if len(variant.sku) > 50:
                    skipped.append((variant.sku, "SKU длиннее 50 символов, O!Market не примет"))
                    continue
                try:
                    self.ensure_omarket_image_extensions(variant)
                except CommandError as exc:
                    skipped.append((variant.sku, str(exc)))
                    continue

                attrs = dict(variant.attributes or {})
                attrs.update(self.omarket_package_fields(variant))
                attrs["omarket_category_id"] = category_id
                attrs["omarket_title"] = self.short_title(variant)
                attrs["omarket_attributes"] = self.omarket_attributes(
                    target_channel,
                    attrs_cache,
                    category_id,
                    variant,
                    options["allow_fetch_attrs"],
                )
                attrs.pop("omarket_filters", None)
                variant.attributes = attrs
                variant.save(update_fields=["attributes"])

                price_obj, _ = ChannelPrice.objects.update_or_create(
                    variant=variant,
                    shop=target_channel.shop,
                    channel=target_channel,
                    defaults={
                        "price": source_price.price,
                        "discount_amount": source_price.discount_amount,
                        "sync_status": ChannelPrice.SyncStatus.PENDING,
                        "last_sync_error": "",
                    },
                )
                prepared.append(price_obj.id)

        self.stdout.write(f"Источник: {source_channel}")
        self.stdout.write(f"Цель: {target_channel}")
        self.stdout.write(f"Подготовлено для O!Market: {len(prepared)}")
        self.stdout.write(f"Пропущено: {len(skipped)}")
        for sku, reason in skipped[:80]:
            self.stdout.write(self.style.WARNING(f"SKIP {sku}: {reason}"))

        if not prepared:
            raise CommandError("Нет товаров для отправки.")

        adapter = get_marketplace_adapter(target_channel)
        batches = [prepared[index : index + options["batch_size"]] for index in range(0, len(prepared), options["batch_size"])]
        for index, batch in enumerate(batches, start=1):
            payload = adapter.build_payload(channel_price_ids=batch)
            self.stdout.write(f"Батч {index}/{len(batches)}: {len(payload['products'])} товаров")
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            if options["dry_run"]:
                continue
            result = adapter.push_products(channel_price_ids=batch)
            self.stdout.write(self.style.SUCCESS(f"Отправлено в O!Market, батч {index}: {result}"))
            self.print_import_status(adapter, result)

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: ChannelPrice созданы/обновлены, но запрос в O!Market не отправлен."))

    def get_channel(self, channel_id, adapter_key, require_branch):
        if channel_id:
            channel = Channel.objects.filter(id=channel_id).first()
        else:
            channel = Channel.objects.filter(adapter_key=adapter_key, is_active=True).first()
        if not channel:
            raise CommandError(f"Канал {adapter_key!r} не найден.")
        missing = []
        if not channel.api_url:
            missing.append("api_url")
        if not channel.api_token:
            missing.append("api_token")
        if require_branch and not channel.branch_id:
            missing.append("branch_id")
        if missing:
            raise CommandError(f"У канала {channel} не заполнено: {', '.join(missing)}.")
        return channel

    def source_prices(self, source_channel, only_categories):
        prices = (
            ChannelPrice.objects.filter(
                shop=source_channel.shop,
                channel=source_channel,
                variant__is_active=True,
                price__gte=Decimal("0.01"),
            )
            .select_related("variant__product", "variant__color", "variant__memory", "variant__size")
            .prefetch_related("variant__images")
            .order_by("variant__product__category", "variant__sku")
        )
        categories = set(only_categories)
        if categories:
            prices = prices.filter(variant__product__category__in=categories)
        else:
            prices = prices.filter(
                variant__product__brand_name__in=["Apple", "Garmin", "Xiaomi", "POCO", "Huawei", "Яндекс"],
                variant__product__category__in=[
                    "Смартфоны",
                    "Планшеты",
                    "Аксессуары для планшетов",
                    "Наушники",
                    "Смарт-часы",
                    "Фитнес-трекеры",
                    "Спортивные аксессуары",
                    "Умные весы",
                    "Велоаксессуары",
                    "Автоэлектроника",
                    "Поисковые метки",
                    "Аксессуары",
                    "Ноутбуки",
                    "Компьютеры",
                    "Умные колонки",
                    "Очистители воздуха",
                ],
            )
        return list(prices)

    def skip_reason(self, variant, shop):
        text = " ".join(
            str(value)
            for value in [
                variant.sku,
                variant.product.name,
                variant.attributes.get("Состояние") if variant.attributes else "",
            ]
        ).upper()
        if "B/U" in text or "Б/У" in text or "DAMAGED" in text:
            return "Б/У или damaged не грузим на маркет"
        if variant.images.count() < 1:
            return "нет фото"
        stock = variant.stocks.filter(shop=shop).first()
        if stock and stock.marketplace_quantity <= 0:
            return "нулевой остаток"
        return ""

    def ensure_omarket_image_extensions(self, variant):
        images = list(variant.images.all())
        if not images:
            raise CommandError("нет фото")
        for image in images:
            suffix = Path(urlparse(image.image.name).path).suffix.lower()
            if suffix in ALLOWED_OMARKET_IMAGE_SUFFIXES:
                continue
            try:
                image.image.open("rb")
                source_image = Image.open(image.image).convert("RGBA")
            except OSError as exc:
                raise CommandError(f"не удалось открыть фото для конвертации: {exc}") from exc
            canvas = Image.new("RGBA", source_image.size, "WHITE")
            canvas.alpha_composite(source_image)
            output = BytesIO()
            canvas.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
            new_name = f"{Path(image.image.name).stem}.jpg"
            image.image.save(new_name, ContentFile(output.getvalue()), save=False)
            image.save(update_fields=["image"])

    def resolve_category_ids(self, channel, tree):
        category_ids = {"Смартфоны": 16}
        for crm_category, candidates in CATEGORY_CANDIDATES.items():
            if crm_category in category_ids:
                continue
            found = self.find_category(tree, candidates)
            if found:
                category_ids[crm_category] = int(found["id"])
        return category_ids

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

    def omarket_package_fields(self, variant):
        category = variant.product.category
        if category == "Смартфоны":
            return {"omarket_width": 8, "omarket_height": 17, "omarket_length": 2, "omarket_weight": 0.35}
        if category == "Планшеты":
            return {"omarket_width": 20, "omarket_height": 28, "omarket_length": 3, "omarket_weight": 0.9}
        if category == "Аксессуары для планшетов":
            return {"omarket_width": 23, "omarket_height": 30, "omarket_length": 4, "omarket_weight": 0.8}
        if category == "Наушники":
            return {"omarket_width": 10, "omarket_height": 10, "omarket_length": 5, "omarket_weight": 0.3}
        if category == "Умные весы":
            return {"omarket_width": 35, "omarket_height": 35, "omarket_length": 5, "omarket_weight": 2.5}
        if category == "Автоэлектроника":
            return {"omarket_width": 12, "omarket_height": 10, "omarket_length": 8, "omarket_weight": 0.6}
        if category == "Поисковые метки":
            return {"omarket_width": 8, "omarket_height": 8, "omarket_length": 3, "omarket_weight": 0.15}
        if category == "Аксессуары":
            return {"omarket_width": 12, "omarket_height": 10, "omarket_length": 4, "omarket_weight": 0.3}
        if category == "Ноутбуки":
            return {"omarket_width": 38, "omarket_height": 28, "omarket_length": 8, "omarket_weight": 2.5}
        if category == "Компьютеры":
            product_name = variant.product.name.lower()
            if "imac" in product_name or "iMac" in variant.product.name:
                return {"omarket_width": 65, "omarket_height": 50, "omarket_length": 20, "omarket_weight": 7.0}
            if "mac mini" in product_name:
                return {"omarket_width": 20, "omarket_height": 20, "omarket_length": 10, "omarket_weight": 1.5}
            return {"omarket_width": 45, "omarket_height": 35, "omarket_length": 20, "omarket_weight": 4.0}
        if category == "Умные колонки":
            return {"omarket_width": 25, "omarket_height": 25, "omarket_length": 25, "omarket_weight": 3.0}
        if category == "Очистители воздуха":
            return {"omarket_width": 35, "omarket_height": 65, "omarket_length": 35, "omarket_weight": 6.0}
        if category in {"Велоаксессуары", "Спортивные аксессуары"}:
            return {"omarket_width": 18, "omarket_height": 12, "omarket_length": 8, "omarket_weight": 0.5}
        return {"omarket_width": 10, "omarket_height": 10, "omarket_length": 7, "omarket_weight": 0.35}

    def short_title(self, variant):
        title = variant.product.name
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) <= 100:
            return title
        memory = variant.memory.volume if variant.memory_id else ""
        color = variant.color.name if variant.color_id else ""
        size = variant.size.name if variant.size_id else ""
        bits = [variant.product.brand_name, variant.attributes.get("Модель") if variant.attributes else "", memory, size, color]
        compact = " ".join(str(bit).strip() for bit in bits if bit).strip()
        return compact[:100] if compact else title[:100]

    def omarket_attributes(self, channel, attrs_cache, category_id, variant, allow_fetch):
        cached_attrs = attrs_cache.get(str(category_id))
        if cached_attrs is None and allow_fetch:
            try:
                cached_attrs = self.fetch_category_attributes(channel, category_id)
            except CommandError as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f"Не удалось получить attrs O!Market для category_id={category_id}: {exc}. "
                        "Продолжаю без omarket_attributes."
                    )
                )
                cached_attrs = []
            attrs_cache[str(category_id)] = cached_attrs
        desired = self.desired_values(variant)
        matched = self.match_omarket_attributes(cached_attrs or [], desired)
        if category_id == 16:
            matched = self.merge_missing_attributes(
                matched,
                [{"attribute_id": key, "value_id": value} for key, value in STATIC_SMARTPHONE_ATTRIBUTES.items()],
            )
            memory = variant.memory.volume if variant.memory_id else (variant.attributes or {}).get("Память", "")
            memory_static = self.smartphone_memory_static(memory)
            if memory_static:
                matched = self.merge_missing_attributes(matched, [{"attribute_id": 4070, "value_id": memory_static}])
        return matched

    def desired_values(self, variant):
        attrs = variant.attributes or {}
        brand = variant.product.brand_name
        model = attrs.get("Модель") or variant.product.brand_category or variant.product.name
        memory = variant.memory.volume if variant.memory_id else attrs.get("Память", "")
        color = variant.color.name if variant.color_id else attrs.get("Цвет", "")
        product_type = attrs.get("Тип") or variant.product.category
        values = {
            ("Состояние", "Техническое состояние"): ["Новый", "Идеальное"],
            ("Бренд", "Производитель", "Производители"): [brand],
            ("Тип", "Тип товара", "Гаджеты"): [product_type, variant.product.category],
            ("Модель", "Линейка", "Серия"): [model, variant.product.brand_category],
            ("Цвет", "Цвет товара"): [color, *self.color_aliases(color)],
            ("Память", "Встроенная память", "Объем встроенной памяти", "Объём встроенной памяти"): [
                memory,
                str(memory).replace("GB", " GB"),
                str(memory).replace("GB", " ГБ"),
            ],
            ("Операционная система", "ОС"): [attrs.get("Операционная система"), "iOS" if brand == "Apple" else ""],
            ("Разъем", "Разъём", "Интерфейс", "Порт зарядки"): [attrs.get("Разъем"), "USB-C", "USB Type-C"],
            ("Bluetooth", "Беспроводная связь"): [attrs.get("Беспроводная связь"), "Bluetooth"],
            ("Материал корпуса", "Материал"): [attrs.get("Материал корпуса"), attrs.get("Материал")],
            ("Диагональ экрана", "Диагональ"): [attrs.get("Диагональ экрана"), attrs.get("Экран")],
            ("Процессор", "Чип"): [attrs.get("Процессор"), attrs.get("Чип")],
            ("Шумоподавление", "Активное шумоподавление"): ["Да", "Есть"] if "ANC" in variant.product.name.upper() else [],
        }
        return {labels: [value for value in candidates if value] for labels, candidates in values.items()}

    def smartphone_memory_static(self, memory):
        normalized = str(memory).replace(" ", "").upper()
        return {
            "128GB": 66574,
            "256GB": 66575,
            "512GB": 66576,
            "1TB": 66577,
        }.get(normalized)

    def merge_missing_attributes(self, attributes, defaults):
        used = {item["attribute_id"] for item in attributes}
        return [*attributes, *[item for item in defaults if item["attribute_id"] not in used]]

    def load_attrs_cache(self, path):
        attrs_path = self.resolve_path(path)
        if not attrs_path:
            return {}
        text = attrs_path.read_text(encoding="utf-8")
        json_start = min([index for index in [text.find("["), text.find("{")] if index >= 0], default=-1)
        if json_start > 0:
            text = text[json_start:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Не удалось прочитать {attrs_path}: {exc}") from exc
        if isinstance(data, list):
            return {"16": data}
        if isinstance(data, dict):
            return {str(key): value for key, value in data.items()}
        return {}

    def resolve_path(self, path):
        original = Path(path)
        candidates = [original]
        if not original.is_absolute():
            candidates.extend([Path.cwd() / original, Path("/app") / original, Path("/tmp") / original])
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def fetch_category_tree(self, channel):
        payload = self.send_omarket_json(channel, "api/mia/v1/category/tree")
        return payload.get("result") or []

    def fetch_category_attributes(self, channel, category_id):
        payload = self.send_omarket_json(channel, f"api/mia/v1/category/attribute?{urlencode({'category': category_id})}")
        return payload.get("result") or []

    def match_omarket_attributes(self, attributes, desired_values):
        selected = []
        selected_attribute_ids = set()
        self.match_omarket_attributes_recursive(attributes, desired_values, selected, selected_attribute_ids)
        return selected

    def match_omarket_attributes_recursive(self, attributes, desired_values, selected, selected_attribute_ids):
        for attribute in attributes or []:
            values = self.desired_values_for_attribute(attribute, desired_values)
            if not values:
                continue
            option = self.find_option(self.attribute_options(attribute), values)
            if not option:
                continue
            attribute_id = int(self.object_id(attribute))
            if attribute_id not in selected_attribute_ids:
                selected.append({"attribute_id": attribute_id, "value_id": int(self.object_id(option))})
                selected_attribute_ids.add(attribute_id)
            self.match_omarket_attributes_recursive(
                option.get("attributes") or [],
                desired_values,
                selected,
                selected_attribute_ids,
            )

    def desired_values_for_attribute(self, attribute, desired_values):
        label = self.normalize_search(attribute.get("create_label") or attribute.get("name") or attribute.get("label"))
        for labels, values in desired_values.items():
            normalized_labels = {self.normalize_search(item) for item in labels}
            if label in normalized_labels or any(self.safe_contains(label, expected) for expected in normalized_labels):
                return values
        return None

    def find_option(self, options, values):
        normalized_values = {self.normalize_search(value) for value in values}
        for option in options:
            value = self.normalize_search(option.get("value") or option.get("name") or option.get("label"))
            if value in normalized_values:
                return option
        for option in options:
            value = self.normalize_search(option.get("value") or option.get("name") or option.get("label"))
            if any(self.safe_contains(value, expected) for expected in normalized_values):
                return option
        return None

    def attribute_options(self, attribute):
        return attribute.get("values") or attribute.get("options") or attribute.get("filter_options") or []

    def object_id(self, item):
        return item.get("id") or item.get("filter_id") or item.get("option_id") or item.get("value_id")

    def color_aliases(self, color):
        normalized = self.normalize_search(color)
        aliases = []
        for key, values in COLOR_VALUES.items():
            if key in normalized:
                aliases.extend(values)
        return aliases

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
            with urlopen(request, timeout=90) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise CommandError(f"O!Market GET {url} вернул {exc.code}: {body}") from exc
        except URLError as exc:
            raise CommandError(f"O!Market GET {url} недоступен: {exc.reason}") from exc
        return json.loads(body) if body else {}

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
        if not actual or not expected:
            return False
        if len(expected) < 3:
            return actual == expected
        return expected in actual or actual in expected
