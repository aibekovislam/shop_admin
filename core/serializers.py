from rest_framework import serializers

from .models import Channel, ChannelPrice, Product, ProductImage, ProductVariant, Stock


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "is_primary", "order"]


class ChannelPriceSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source="channel.name", read_only=True)

    class Meta:
        model = ChannelPrice
        fields = ["id", "channel", "channel_name", "price", "updated_at", "last_synced_at", "last_sync_error"]
        read_only_fields = ["updated_at", "last_synced_at", "last_sync_error"]


class VariantListSerializer(serializers.ModelSerializer):
    """
    Полная выгрузка варианта товара для конкретного магазина:
    название, атрибуты, фото, наличие/опт.цена, цены по всем каналам
    этого магазина. Именно это отдаёт GET /variants/ — то, чем будет
    наполняться Google-таблица.
    """

    product_name = serializers.CharField(source="product.name", read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    wholesale_price = serializers.SerializerMethodField()
    quantity = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()
    channel_prices = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "sku",
            "product_name",
            "attributes",
            "images",
            "wholesale_price",
            "quantity",
            "in_stock",
            "channel_prices",
        ]

    def get_stock(self, obj):
        # избегаем лишнего запроса на каждый variant — self.context содержит
        # заранее посчитанный словарь {variant_id: Stock}, см. views.py
        return self.context.get("stock_by_variant", {}).get(obj.id)

    def get_wholesale_price(self, obj):
        stock = self.get_stock(obj)
        return stock.wholesale_price if stock else None

    def get_in_stock(self, obj):
        stock = self.get_stock(obj)
        return stock.in_stock if stock else False

    def get_quantity(self, obj):
        stock = self.get_stock(obj)
        return stock.quantity if stock else 0

    def get_channel_prices(self, obj):
        prices = self.context.get("prices_by_variant", {}).get(obj.id, [])
        return ChannelPriceSerializer(prices, many=True).data


class BulkUpdateItemSerializer(serializers.Serializer):
    """
    Один элемент из payload'а bulk_update. Валидируется отдельно от
    остальных — так один некорректный элемент не блокирует остальные
    (см. bulk_update view, где каждый item обрабатывается в своей
    транзакции с построчным статусом в ответе).
    """

    variant_id = serializers.IntegerField()
    wholesale_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=0, required=False)
    in_stock = serializers.BooleanField(required=False)
    # channel_id -> price, например {"3": "79990.00", "4": "81990.00"}
    channel_prices = serializers.DictField(
        child=serializers.DecimalField(max_digits=10, decimal_places=2), required=False
    )


class CreateVariantSerializer(serializers.Serializer):
    """
    Создание нового товара (Product + ProductVariant + Stock) за один вызов —
    именно этим будет пользоваться кнопка "Добавить товар" в Google Sheets.
    Channel prices не создаются здесь намеренно: у нового товара их можно
    проставить последующим bulk_update, когда цены по каналам известны.
    """

    product_name = serializers.CharField(max_length=255)
    category = serializers.CharField(max_length=255, required=False, allow_blank=True)
    sku = serializers.CharField(max_length=100)
    attributes = serializers.DictField(required=False, default=dict)
    wholesale_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=0, required=False, default=0)
    in_stock = serializers.BooleanField(required=False, default=False)

    def validate_sku(self, value):
        if ProductVariant.objects.filter(sku=value).exists():
            raise serializers.ValidationError("SKU already exists.")
        return value
