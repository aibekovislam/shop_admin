import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.management.commands.sync_shat_loaded_to_omarket import Command as OMarketLookup
from core.marketplace.catalog_attributes import has_brand_dependencies
from core.marketplace.factory import get_marketplace_adapter
from core.models import Channel


CATEGORIES = {
    "Смартфоны", "Планшеты", "Планшетные компьютеры", "Наушники", "Bluetooth-наушники",
    "Смарт-часы", "Умные часы", "Ноутбуки", "Ноутбуки и ультрабуки", "Умные колонки",
    "Портативная акустика", "Акустика", "Очистители воздуха", "Фотоаппараты",
    "Экшн-камеры", "Стилусы", "Зарядные устройства", "Компьютерные мыши", "Мыши",
    "Геймпады", "Джойстики", "Стайлеры", "Фены", "Умные очки", "Солнцезащитные очки",
    "Аксессуары для планшетов", "Колонки", "Фены и приборы для укладки", "Цифровые фотоаппараты",
}


class Command(BaseCommand):
    help = "Экспортирует схему TURAN O!Market и проверяет каналы без записи в БД и отправки товаров."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="turan_market_schema.json")

    def handle(self, *args, **options):
        channels = list(Channel.objects.filter(id__in=[8, 11], is_active=True).select_related("shop"))
        if {c.id for c in channels} != {8, 11} or any(c.shop_id != 3 or c.shop.name.upper() != "TURAN" for c in channels):
            raise CommandError("Ожидались активные каналы 8 и 11 магазина TURAN (shop_id=3)")
        if any(c.adapter_key != {8: "omarket", 11: "turan_bakai"}[c.id] for c in channels):
            raise CommandError("Ключи адаптеров каналов TURAN изменились; экспорт остановлен")
        for channel in channels:
            get_marketplace_adapter(channel).validate_channel()
        channel = next(c for c in channels if c.id == 8)
        lookup = OMarketLookup(stdout=self.stdout, stderr=self.stderr)
        tree = lookup.fetch_category_tree(channel)
        selected = {}

        def walk(nodes, parents=()):
            for node in nodes:
                path = (*parents, node.get("name", ""))
                if node.get("name") in CATEGORIES:
                    selected[str(node["id"])] = " / ".join(path)
                walk(node.get("sub_categories") or node.get("children") or [], path)

        walk(tree)
        selected.setdefault("16", "Смартфоны")
        result = {
            "channels": [{"id": c.id, "shop_id": c.shop_id, "name": c.name,
                          "adapter_key": c.adapter_key, "branch_id": c.branch_id} for c in channels],
            "tree": tree, "category_paths": selected, "attributes": {}, "errors": {},
        }
        output = Path(options["output"])
        for category_id, path in selected.items():
            try:
                attributes = lookup.fetch_category_attributes(channel, int(category_id))
                result["attributes"][category_id] = attributes
                self.stdout.write(f"{category_id}: {path}: {len(attributes)} полей")
                if category_id == "16" and not has_brand_dependencies(attributes):
                    result["errors"][category_id] = "API вернул смартфоны без вложенных attributes брендов"
            except Exception as exc:
                result["errors"][category_id] = str(exc)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(f"Схема сохранена: {output}. Ошибок: {len(result['errors'])}. Товары не отправлялись.")
