import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .base import MarketplaceAdapter
from core.models import ChannelPrice, Stock


class BakaiMarketAdapter(MarketplaceAdapter):
    DEFAULT_API_URL = "https://api.bakai.store/product-service-go/v1/merchant-api/create"
    BRAND_KEYS = ("Бренд", "brand", "Производитель", "Производители")
    EXCLUDED_ATTRIBUTE_PREFIXES = ("omarket_", "bakai_")

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

        prices = (
            ChannelPrice.objects.filter(
                shop=self.shop,
                channel=self.channel,
                variant__is_active=True,
                price__gte=Decimal("0.01"),
            )
            .select_related("variant__product")
            .prefetch_related("variant__images")
        )
        if channel_price_ids is not None:
            prices = prices.filter(id__in=channel_price_ids)
        prices = list(prices[:1000])

        stock_by_variant = {
            stock.variant_id: stock
            for stock in Stock.objects.filter(
                shop=self.shop,
                variant_id__in=[price.variant_id for price in prices],
            )
        }
        public_base_url = getattr(settings, "PUBLIC_MEDIA_BASE_URL", "https://shop.kkode.site").rstrip("/")

        products = []
        errors = []
        for price in prices:
            variant = price.variant
            product_model = variant.product
            attrs = variant.attributes or {}
            stock = stock_by_variant.get(variant.id)
            images = [f"{public_base_url}{image.image.url}" for image in variant.images.all()]
            brand_name = self.get_brand_name(product_model, attrs)
            attributes = self.build_attributes(product_model, attrs)

            product_errors = self.validate_product(product_model, variant, images, brand_name)
            if product_errors:
                errors.append(f"{variant.sku}: {', '.join(product_errors)}")
                continue

            item = {
                "sku": variant.sku,
                "name": product_model.name,
                "price": float(price.price),
                "category_name": product_model.category,
                "brand_name": brand_name,
                "description": product_model.description,
                "images": images,
                "branch_id": self.channel.branch_id,
                "quantity": stock.marketplace_quantity if stock else 0,
                "is_active": variant.is_active,
            }
            if price.discount_amount:
                item["discount_amount"] = float(price.discount_amount)
            if variant.similar_products_sku_list:
                item["similar_products_sku"] = variant.similar_products_sku_list
            if attributes:
                item["attributes"] = attributes

            products.append(item)

        if errors:
            raise ValidationError(errors)
        if not products:
            raise ValidationError("Нет товаров с ценой для выгрузки в Bakai Market.")

        return {"products": products}

    def get_brand_name(self, product, attrs):
        if product.brand_name:
            return product.brand_name
        for key in self.BRAND_KEYS:
            value = attrs.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    def build_attributes(self, product, attrs):
        attributes = []
        if product.brand_category:
            attributes.append({"name": "Категория бренда", "value": product.brand_category})
        for key, value in attrs.items():
            key = str(key).strip()
            if not key or value in (None, ""):
                continue
            if key in self.BRAND_KEYS:
                continue
            if key.startswith(self.EXCLUDED_ATTRIBUTE_PREFIXES):
                continue
            attributes.append({"name": key, "value": str(value)})
        return attributes

    def validate_product(self, product, variant, images, brand_name):
        errors = []
        if not variant.sku:
            errors.append("не указан SKU")
        if not 7 <= len(product.name or "") <= 250:
            errors.append("название должно быть 7-250 символов")
        if not product.category:
            errors.append("не указана категория")
        if not brand_name:
            errors.append("для Bakai нужно указать бренд: Бренд, brand, Производитель или Производители")
        if len(product.description or "") < 50:
            errors.append("описание должно быть минимум 50 символов")
        if len(images) < 3:
            errors.append("нужно минимум 3 фото")
        invalid_images = [
            image_url for image_url in images if not urlparse(image_url).path.lower().endswith((".jpg", ".png", ".webp"))
        ]
        if invalid_images:
            errors.append("фото должны быть прямыми ссылками .jpg, .png или .webp")
        return errors

    def push_products(self, channel_price_ids=None):
        payload = self.build_payload(channel_price_ids=channel_price_ids)
        request = Request(
            self.channel.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.channel.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ShopAdminBakaiMarketImporter/1.0",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=30) as response:
                status_code = response.status
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8")
            raise Exception(f"Bakai Market error {exc.code}: {response_body}") from exc
        except URLError as exc:
            raise Exception(f"Bakai Market connection error: {exc.reason}") from exc

        if status_code not in (200, 201, 202):
            raise Exception(f"Bakai Market error {status_code}: {response_body}")

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
