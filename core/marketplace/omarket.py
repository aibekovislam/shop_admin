import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .base import MarketplaceAdapter
from core.models import ChannelPrice, Stock


class OMarketAdapter(MarketplaceAdapter):
    DEFAULT_API_BASE_URL = "https://api-market.o.kg/"
    IMPORT_PATH = "api/mia/v1/product/import/create-or-update/"
    STATUS_PATH = "api/mia/v1/product/import/info/{task_id}"

    def validate_channel(self):
        errors = []
        if not self.channel.api_url:
            errors.append("У канала не указан API URL.")
        if not self.channel.api_token:
            errors.append("У канала не указан API token.")
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
        prices = list(prices[:100])

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
            stock = stock_by_variant.get(variant.id)
            attrs = variant.attributes or {}
            images = [
                {
                    "type": "url",
                    "image": f"{public_base_url}{image.image.url}",
                    **({"is_primary_image": True} if index == 0 else {}),
                }
                for index, image in enumerate(variant.images.all()[:10])
            ]

            product_errors = self.validate_product(product_model, variant, attrs, images)
            if product_errors:
                errors.append(f"{variant.sku}: {', '.join(product_errors)}")
                continue

            item = {
                "sku": variant.sku,
                "title": product_model.name,
                "description": product_model.description or "",
                "category_id": int(attrs["omarket_category_id"]),
                "price": float(price.price),
                "quantity": stock.marketplace_quantity if stock else 0,
                "images": images,
                "width": self.positive_number(attrs.get("omarket_width", 1)),
                "height": self.positive_number(attrs.get("omarket_height", 1)),
                "length": self.positive_number(attrs.get("omarket_length", 1)),
                "weight": self.positive_number(attrs.get("omarket_weight", 1)),
                "currency": attrs.get("omarket_currency", "KGS"),
                "is_delivery_enabled": attrs.get("omarket_is_delivery_enabled", True),
            }

            optional_fields = {
                "location_id": attrs.get("omarket_location_id"),
                "discount_type": attrs.get("omarket_discount_type"),
                "discount_value": attrs.get("omarket_discount_value"),
                "attributes": attrs.get("omarket_attributes"),
            }
            for key, value in optional_fields.items():
                if value not in (None, "", []):
                    item[key] = value

            products.append(item)

        if errors:
            raise ValidationError(errors)
        if not products:
            raise ValidationError("Нет товаров с ценой для выгрузки в O!Market.")

        return {"products": products}

    def validate_product(self, product, variant, attrs, images):
        errors = []
        if not variant.sku or len(variant.sku) > 50:
            errors.append("SKU обязателен и должен быть до 50 символов")
        if not product.name or len(product.name) > 100:
            errors.append("название обязательно и должно быть до 100 символов")
        if len(product.description or "") > 1000:
            errors.append("описание должно быть до 1000 символов")
        if not attrs.get("omarket_category_id"):
            errors.append("в attributes нужно указать omarket_category_id")
        elif not self.is_positive_integer(attrs["omarket_category_id"]):
            errors.append("omarket_category_id должен быть положительным числом")
        for field_name in ("omarket_width", "omarket_height", "omarket_length", "omarket_weight"):
            if attrs.get(field_name) in (0, "0"):
                errors.append(f"{field_name} должен быть больше 0")
            elif attrs.get(field_name) not in (None, "") and not self.is_positive_number(attrs[field_name]):
                errors.append(f"{field_name} должен быть числом больше 0")
        if not images:
            errors.append("нужно минимум 1 фото")
        invalid_images = [
            image["image"]
            for image in images
            if not urlparse(image["image"]).path.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        if invalid_images:
            errors.append("фото должны быть прямыми ссылками .jpg/.jpeg или .png")
        omarket_attributes = attrs.get("omarket_attributes")
        if omarket_attributes not in (None, "") and not isinstance(omarket_attributes, list):
            errors.append("omarket_attributes должен быть списком")
        return errors

    def push_products(self, channel_price_ids=None):
        payload = self.build_payload(channel_price_ids=channel_price_ids)
        response = self.send_json_request("POST", self.import_url(), payload)

        synced_prices = ChannelPrice.objects.filter(
            shop=self.shop,
            channel=self.channel,
            variant__is_active=True,
            price__gte=Decimal("0.01"),
        )
        if channel_price_ids is not None:
            synced_prices = synced_prices.filter(id__in=channel_price_ids)
        synced_prices.update(last_synced_at=timezone.now(), last_sync_error="")

        return response or {"status": "ok", "sent": len(payload["products"])}

    def get_import_status(self, task_id):
        return self.send_json_request("GET", urljoin(self.api_base_url(), self.STATUS_PATH.format(task_id=task_id)))

    def import_url(self):
        api_url = self.channel.api_url.rstrip("/") + "/"
        if api_url.endswith(self.IMPORT_PATH):
            return api_url
        return urljoin(api_url, self.IMPORT_PATH)

    def api_base_url(self):
        return self.channel.api_url.rstrip("/") + "/"

    def send_json_request(self, method, url, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=data,
            headers={
                "X-Access-Token": self.channel.api_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "ShopAdminOMarketImporter/1.0",
            },
            method=method,
        )

        try:
            with urlopen(request, timeout=30) as response:
                status_code = response.status
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8")
            raise Exception(f"O!Market error {exc.code}: {response_body}") from exc
        except URLError as exc:
            raise Exception(f"O!Market connection error: {exc.reason}") from exc

        if status_code not in (200, 201, 202):
            raise Exception(f"O!Market error {status_code}: {response_body}")
        if not response_body:
            return {}
        try:
            return json.loads(response_body)
        except json.JSONDecodeError:
            return {"status": "ok", "response": response_body}

    def positive_number(self, value):
        return float(value) if "." in str(value) else int(value)

    def is_positive_number(self, value):
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False

    def is_positive_integer(self, value):
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return False

    def pull_orders(self):
        pass
