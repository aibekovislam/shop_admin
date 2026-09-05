"""Pure validation helpers for the isolated WEBSITE TURAN import."""

import hashlib
from decimal import Decimal
from urllib.parse import urlparse

from core.marketplace.catalog_attributes import match_attributes
from core.turan_catalog import USED, identity


CATEGORY_IDS = {
    "Смартфоны": 16, "Ноутбуки": 5333, "Наушники": 844,
    "Планшеты": 5363, "Стилусы": 5365, "Умные колонки": 5375,
    "Акустические системы": 5378, "Смарт-часы": 5455,
    "Умные часы": 5455, "Мыши": 5513, "Зарядные устройства": 5349,
    "Экшн-камеры": 5427, "Фотокамеры": 5429,
    "Фотокамеры моментальной печати": 5426, "Игровые контроллеры": 5480,
    "Очистители и увлажнители": 5161, "Фены": 5208, "Щипцы": 5206,
}


def catalog_sku(name):
    return "TURAN-" + hashlib.sha256(identity(name).encode()).hexdigest()[:24].upper()


def prepare_card(row, card, schema):
    if USED.search(row["name"]) or USED.search(card.get("name", "")):
        raise ValueError("Б/У и поврежденные товары запрещены")
    attrs = dict(card.get("attributes") or {})
    condition = str(attrs.get("Состояние", "")).strip().casefold()
    if condition not in {"новый", "новое", "новые", "new"}:
        raise ValueError("Не подтверждено новое состояние товара")
    price = Decimal(str(row.get("price_kgs")))
    if not price.is_finite() or price <= 0:
        raise ValueError("Нет положительной цены в сомах")
    if not 7 <= len(card.get("name", "")) <= 100:
        raise ValueError("Название должно быть длиной 7–100 символов")
    if not 50 <= len(card.get("description", "")) <= 1000:
        raise ValueError("Описание должно быть длиной 50–1000 символов")
    if not card.get("brand") or not card.get("category"):
        raise ValueError("Нет бренда или категории")
    category_id = card.get("category_id") or attrs.get("omarket_category_id") or CATEGORY_IDS.get(card["category"])
    if str(category_id) not in schema:
        raise ValueError(f"Нет схемы категории {category_id}: {card['category']}")
    images = card.get("images") or []
    if len(images) != 3 or len(set(images)) != 3:
        raise ValueError("Нужны три разные фотографии")
    for url in images:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or not parsed.path.lower().endswith((".jpg", ".png")):
            raise ValueError("Для обоих маркетов нужны прямые HTTPS-ссылки JPG или PNG")
    # Never inherit IDs belonging to another marketplace account or stale schema.
    attrs = {key: value for key, value in attrs.items() if not key.startswith(("omarket_", "bakai_", "turan_"))}
    values, unresolved = match_attributes(schema[str(category_id)], card.get("market_specs") or attrs)
    required_missing = [item for item in unresolved if item.get("required") or item.get("reason") == "нет подтвержденного значения"]
    if required_missing:
        raise ValueError(f"Не заполнены обязательные характеристики: {required_missing}")
    attrs.update(omarket_category_id=int(category_id), omarket_attributes=values,
                 omarket_currency="KGS", omarket_title=card["name"])
    return {**card, "sku": catalog_sku(row["name"]), "source_name": row["name"],
            "quantity": row["quantity"], "price_kgs": str(price), "attributes": attrs,
            "attribute_warnings": unresolved, "pricing": row}
