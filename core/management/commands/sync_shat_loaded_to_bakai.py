import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.marketplace.factory import get_marketplace_adapter
from core.models import Channel, ChannelPrice


LOADED_CATEGORIES = [
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
]


class Command(BaseCommand):
    help = "Переносит уже загруженные SHAT товары из M-Market в Bakai Market."

    def add_arguments(self, parser):
        parser.add_argument("--source-adapter-key", default="mmarket", help="Канал-источник с уже загруженными товарами.")
        parser.add_argument("--target-adapter-key", default="bakai", help="Канал Bakai Market.")
        parser.add_argument("--source-channel-id", type=int, help="ID M-Market канала, если adapter_key не подходит.")
        parser.add_argument("--target-channel-id", type=int, help="ID Bakai канала.")
        parser.add_argument("--batch-size", type=int, default=1000, help="Размер батча импорта Bakai.")
        parser.add_argument("--dry-run", action="store_true", help="Подготовить payload без отправки в Bakai Market.")
        parser.add_argument("--only-category", action="append", default=[], help="Ограничить CRM-категорию, можно несколько раз.")

    def handle(self, *args, **options):
        source_channel = self.get_channel(options["source_channel_id"], options["source_adapter_key"], require_branch=True)
        target_channel = self.get_channel(options["target_channel_id"], options["target_adapter_key"], require_branch=True)
        if source_channel.shop_id != target_channel.shop_id:
            raise CommandError("Канал M-Market и Bakai должны быть у одного магазина.")

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
        self.stdout.write(f"Подготовлено для Bakai Market: {len(prepared)}")
        self.stdout.write(f"Пропущено: {len(skipped)}")
        for sku, reason in skipped[:100]:
            self.stdout.write(self.style.WARNING(f"SKIP {sku}: {reason}"))

        if not prepared:
            raise CommandError("Нет товаров для отправки.")

        adapter = get_marketplace_adapter(target_channel)
        batches = [prepared[index : index + options["batch_size"]] for index in range(0, len(prepared), options["batch_size"])]
        for index, batch in enumerate(batches, start=1):
            try:
                payload = adapter.build_payload(channel_price_ids=batch)
            except ValidationError as exc:
                raise CommandError(f"Bakai validation error: {exc}") from exc
            self.stdout.write(f"Батч {index}/{len(batches)}: {len(payload['products'])} товаров")
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            if options["dry_run"]:
                continue
            result = adapter.push_products(channel_price_ids=batch)
            self.stdout.write(self.style.SUCCESS(f"Отправлено в Bakai Market, батч {index}: {result}"))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry-run: ChannelPrice созданы/обновлены, но запрос в Bakai Market не отправлен."))

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
                variant__product__brand_name__in=["Apple", "Garmin"],
                variant__product__category__in=LOADED_CATEGORIES,
            )
        return list(prices)

    def skip_reason(self, variant, shop):
        attrs = variant.attributes or {}
        text = " ".join(
            str(value)
            for value in [
                variant.sku,
                variant.product.name,
                attrs.get("Состояние", ""),
            ]
        ).upper()
        if "B/U" in text or "Б/У" in text or "DAMAGED" in text:
            return "Б/У или damaged не грузим на маркет"
        if len(variant.images.all()) < 3:
            return "меньше 3 фото"
        stock = variant.stocks.filter(shop=shop).first()
        if not stock or stock.marketplace_quantity <= 0:
            return "нулевой остаток"
        if not variant.product.brand_name and not any(attrs.get(key) for key in ("Бренд", "brand", "Производитель", "Производители")):
            return "нет бренда"
        if len(variant.product.description or "") < 50:
            return "короткое описание"
        return ""
