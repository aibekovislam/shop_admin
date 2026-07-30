from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import HasShopAPIKey
from .models import Channel, ChannelPrice, Product, ProductVariant, Shop, Stock
from .serializers import (
    BulkUpdateItemSerializer,
    CreateVariantSerializer,
    VariantListSerializer,
)


class ShopScopedAPIView(APIView):
    """
    Общая база для всех эндпоинтов /api/shops/<shop_id>/...

    Проверяет, что ключ из Authorization относится именно к тому shop_id,
    который указан в URL — иначе таблица магазина 1 могла бы физически
    отправить запрос с URL магазина 2 и, будь у неё чужой ключ, поменять
    чужие данные. Здесь же дополнительно убеждаемся, что ключ и URL
    совпадают, а не полагаемся только на permission-класс.
    """

    permission_classes = [HasShopAPIKey]

    def get_shop(self, shop_id):
        shop = get_object_or_404(Shop, id=shop_id)
        if self.request.auth.shop_id != shop.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("API key does not match this shop.")
        return shop


class VariantListView(ShopScopedAPIView):
    """
    GET /api/shops/<shop_id>/variants/

    Полная выгрузка каталога магазина: то, чем заполняется Google-таблица
    при нажатии "Обновить данные".
    """

    def get(self, request, shop_id):
        shop = self.get_shop(shop_id)

        variants = (
            ProductVariant.objects.filter(stocks__shop=shop)
            .select_related("product")
            .prefetch_related("images")
            .distinct()
        )

        stock_by_variant = {s.variant_id: s for s in Stock.objects.filter(shop=shop)}

        prices_by_variant = {}
        for price in ChannelPrice.objects.filter(shop=shop).select_related("channel"):
            prices_by_variant.setdefault(price.variant_id, []).append(price)

        serializer = VariantListSerializer(
            variants,
            many=True,
            context={"stock_by_variant": stock_by_variant, "prices_by_variant": prices_by_variant},
        )
        return Response(serializer.data)


class BulkUpdateView(ShopScopedAPIView):
    """
    POST /api/shops/<shop_id>/variants/bulk_update/

    Принимает {"changes": [...]}, каждый элемент — variant_id + опционально
    wholesale_price/in_stock/channel_prices. Каждый элемент обрабатывается
    в своей транзакции: один некорректный элемент (например, variant_id не
    существует) не блокирует сохранение остальных — ответ содержит
    построчный статус success/error по каждому элементу.
    """

    def post(self, request, shop_id):
        shop = self.get_shop(shop_id)
        changes = request.data.get("changes", [])

        if not isinstance(changes, list) or not changes:
            return Response(
                {"detail": "'changes' must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST
            )

        results = []
        for raw_item in changes:
            results.append(self._process_one(shop, raw_item))

        return Response({"results": results})

    def _process_one(self, shop, raw_item):
        item_serializer = BulkUpdateItemSerializer(data=raw_item)
        if not item_serializer.is_valid():
            return {
                "variant_id": raw_item.get("variant_id"),
                "status": "error",
                "errors": item_serializer.errors,
            }

        data = item_serializer.validated_data
        variant_id = data["variant_id"]

        try:
            with transaction.atomic():
                variant = ProductVariant.objects.get(id=variant_id)

                if "wholesale_price" in data or "in_stock" in data:
                    stock, _ = Stock.objects.get_or_create(variant=variant, shop=shop)
                    if "wholesale_price" in data:
                        stock.wholesale_price = data["wholesale_price"]
                    if "in_stock" in data:
                        stock.in_stock = data["in_stock"]
                    stock.save()

                for channel_id, price in data.get("channel_prices", {}).items():
                    channel = Channel.objects.get(id=channel_id, shop=shop)
                    ChannelPrice.objects.update_or_create(
                        variant=variant, shop=shop, channel=channel, defaults={"price": price}
                    )

            return {"variant_id": variant_id, "status": "ok"}

        except ProductVariant.DoesNotExist:
            return {"variant_id": variant_id, "status": "error", "errors": "Variant not found."}
        except Channel.DoesNotExist:
            return {"variant_id": variant_id, "status": "error", "errors": "Channel not found for this shop."}
        except Exception as exc:  # noqa: BLE001 — отдаём построчную ошибку, не роняя весь запрос
            return {"variant_id": variant_id, "status": "error", "errors": str(exc)}


class CreateVariantView(ShopScopedAPIView):
    """
    POST /api/shops/<shop_id>/variants/create/

    Создаёт Product + ProductVariant + Stock за один вызов — то, чем
    пользуется кнопка "Добавить товар" в Google Sheets.
    """

    def post(self, request, shop_id):
        shop = self.get_shop(shop_id)
        serializer = CreateVariantSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        with transaction.atomic():
            product = Product.objects.create(
                name=data["product_name"], category=data.get("category", "")
            )
            variant = ProductVariant.objects.create(
                product=product, sku=data["sku"], attributes=data.get("attributes", {})
            )
            Stock.objects.create(
                variant=variant,
                shop=shop,
                wholesale_price=data.get("wholesale_price"),
                in_stock=data.get("in_stock", False),
            )

        return Response(
            {"variant_id": variant.id, "sku": variant.sku, "product_id": product.id},
            status=status.HTTP_201_CREATED,
        )
