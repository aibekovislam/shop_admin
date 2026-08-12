import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .base import MarketplaceAdapter

from core.models import (
    ChannelPrice,
    Stock,
)


class MMarketAdapter(MarketplaceAdapter):
    DEFAULT_API_URL = "https://m-market.kg/api/crm/products/import_products/"
    REQUIRED_SPEC_KEYS = ("Тип", "Производители", "Цвет")

    def __init__(self, channel):
        self.channel = channel
        self.shop = channel.shop

    def validate_channel(self):
        errors = []
        if not self.channel.api_url:
            errors.append("У канала не указан API URL.")
        if not self.channel.api_token:
            errors.append("У канала не указан API token.")
        if not self.channel.branch_id:
            errors.append("У канала не указан branch_id.")
        if errors:
            raise ValidationError(errors)

    def build_payload(self, channel_price_ids=None):
        self.validate_channel()

        products = []
        errors = []

        prices = (
            ChannelPrice.objects.filter(
                shop=self.shop,
                channel=self.channel,
                variant__is_active=True,
                price__gte=Decimal("0.01"),
            )
            .select_related("variant__product")
            .prefetch_related(
                "variant__images",
                "variant__product__colors",
                "variant__product__memories",
                "variant__product__sizes",
            )
        )
        if channel_price_ids is not None:
            prices = prices.filter(id__in=channel_price_ids)
        prices = list(prices)

        stock_by_variant = {
            stock.variant_id: stock
            for stock in Stock.objects.filter(
                shop=self.shop,
                variant_id__in=[price.variant_id for price in prices],
            )
        }

        public_base_url = getattr(settings, "PUBLIC_MEDIA_BASE_URL", "https://shop.kkode.site").rstrip("/")

        for price in prices:
            variant = price.variant
            product_model = variant.product
            stock = stock_by_variant.get(variant.id)

            images = self.build_images(variant, public_base_url)
            specs = self.build_specs(product_model, variant, variant.attributes or {})

            product_errors = self.validate_product(product_model, variant, images, specs)
            if product_errors:
                errors.append(f"{variant.sku}: {', '.join(product_errors)}")
                continue

            product = {
                "sku": variant.sku,
                "name": product_model.name,
                "category": product_model.category,
                "price": str(price.price) if price else "0",
                "description": product_model.description,
                "images": images,
                "specs": specs,
                "stock": [
                    {
                        "quantity": stock.marketplace_quantity if stock else 0,
                        "branch_id": self.channel.branch_id,
                    }
                ],
            }
            if price.discount_amount:
                product["discount"] = str(price.discount_amount)
            if variant.similar_products_sku_list:
                product["similar_products_sku"] = variant.similar_products_sku_list

            products.append(product)

        if errors:
            raise ValidationError(errors)
        if not products:
            raise ValidationError("Нет товаров с ценой для выгрузки в M-Market.")

        return {
            "products": products
        }

    def build_images(self, variant, public_base_url):
        return [f"{public_base_url}{image.image.url}" for image in variant.images.all()]

    def build_specs(self, product, variant, attributes):
        specs = {
            key: value
            for key, value in attributes.items()
            if value and not key.startswith("omarket_")
        }
        normalized_specs = {
            self.normalize_spec_key(key): value
            for key, value in specs.items()
        }

        if product.brand_name and not normalized_specs.get("Производители"):
            normalized_specs["Производители"] = product.brand_name
        if product.name and not normalized_specs.get("Модель"):
            normalized_specs["Модель"] = product.name
        color = self.get_variant_color(variant)
        memory = self.get_variant_memory(variant)
        size = self.get_variant_size(variant)
        if color and not normalized_specs.get("Цвет"):
            normalized_specs["Цвет"] = color.name
        if memory and not normalized_specs.get("Память"):
            normalized_specs["Память"] = memory.volume
        if size and not normalized_specs.get("Размер"):
            normalized_specs["Размер"] = size.name

        if product.brand_category and not normalized_specs.get("Тип"):
            normalized_specs["Тип"] = product.brand_category
        elif product.category and not normalized_specs.get("Тип"):
            normalized_specs["Тип"] = product.category
        if product.brand_name and not normalized_specs.get("Производители"):
            normalized_specs["Производители"] = product.brand_name
        if product.brand_category and not normalized_specs.get("Категория бренда"):
            normalized_specs["Категория бренда"] = product.brand_category

        return normalized_specs

    def get_variant_color(self, variant):
        return variant.color or variant.product.colors.first()

    def get_variant_memory(self, variant):
        return variant.memory or variant.product.memories.first()

    def get_variant_size(self, variant):
        return variant.size or variant.product.sizes.first()

    def normalize_spec_key(self, key):
        aliases = {
            "тип": "Тип",
            "производитель": "Производители",
            "производители": "Производители",
            "бренд": "Производители",
            "brand": "Производители",
            "модель": "Модель",
            "model": "Модель",
            "память": "Память",
            "memory": "Память",
            "цвет": "Цвет",
            "color": "Цвет",
        }
        normalized_key = str(key).strip()
        return aliases.get(normalized_key.lower(), normalized_key)

    def validate_product(self, product, variant, images, specs):
        errors = []
        if not variant.sku:
            errors.append("не указан SKU")
        if not 7 <= len(product.name or "") <= 250:
            errors.append("название должно быть 7-250 символов")
        if not product.category:
            errors.append("не указана категория")
        if len(product.description or "") < 50:
            errors.append("описание должно быть минимум 50 символов")
        if len(images) < 3:
            errors.append("нужно минимум 3 фото")
        invalid_images = [
            image_url for image_url in images if not urlparse(image_url).path.lower().endswith((".jpg", ".png", ".webp"))
        ]
        if invalid_images:
            errors.append("фото должны быть прямыми ссылками .jpg, .png или .webp")
        missing_spec_keys = [key for key in self.REQUIRED_SPEC_KEYS if not specs.get(key)]
        if missing_spec_keys:
            errors.append(
                "для M-Market нужно заполнить характеристики: "
                + ", ".join(missing_spec_keys)
            )
        return errors

    def push_products(self, channel_price_ids=None):
        payload = self.build_payload(channel_price_ids=channel_price_ids)

        request = Request(
            self.channel.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Token {self.channel.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ShopAdminMMarketImporter/1.0",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30) as response:
                status_code = response.status
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8")
            raise Exception(f"MMarket error {exc.code}: {response_body}") from exc
        except URLError as exc:
            raise Exception(f"MMarket connection error: {exc.reason}") from exc

        if status_code not in (200, 201, 202):
            raise Exception(f"MMarket error {status_code}: {response_body}")

        synced_prices = ChannelPrice.objects.filter(
            shop=self.shop,
            channel=self.channel,
            variant__is_active=True,
            price__gte=Decimal("0.01"),
        )
        if channel_price_ids is not None:
            synced_prices = synced_prices.filter(id__in=channel_price_ids)
        synced_prices.update(
            sync_status=ChannelPrice.SyncStatus.SUCCESS,
            last_synced_at=timezone.now(),
            last_sync_error="",
        )

        if not response_body:
            return {"status": "ok", "sent": len(payload["products"])}

        try:
            return json.loads(response_body)
        except json.JSONDecodeError:
            return {"status": "ok", "sent": len(payload["products"]), "response": response_body}

    def pull_orders(self):
        pass
