from rest_framework import serializers

from .models import Channel, ChannelPrice, Memory, Product, ProductColor, ProductImage, ProductSize, ProductVariant, Stock


class ProductImageSerializer(serializers.ModelSerializer):
    color_name = serializers.CharField(source="color.name", read_only=True)

    class Meta:
        model = ProductImage
        fields = ["id", "image", "color", "color_name"]


class ProductColorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductColor
        fields = ["id", "name", "hash_code"]


class MemorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Memory
        fields = ["id", "volume"]


class ProductSizeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSize
        fields = ["id", "name"]


class ChannelPriceSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source="channel.name", read_only=True)

    class Meta:
        model = ChannelPrice
        fields = [
            "id",
            "channel",
            "channel_name",
            "price",
            "discount_amount",
            "sync_status",
            "updated_at",
            "last_synced_at",
            "last_sync_error",
        ]
        read_only_fields = ["sync_status", "updated_at", "last_synced_at", "last_sync_error"]


class VariantListSerializer(serializers.ModelSerializer):
    """
    Полная выгрузка варианта товара для конкретного магазина:
    название, атрибуты, фото, наличие/опт.цена, цены по всем каналам
    этого магазина. Именно это отдаёт GET /variants/ — то, чем будет
    наполняться Google-таблица.
    """

    product_name = serializers.CharField(source="product.name", read_only=True)
    color_name = serializers.CharField(source="color.name", read_only=True)
    memory_volume = serializers.CharField(source="memory.volume", read_only=True)
    size_name = serializers.CharField(source="size.name", read_only=True)
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
            "color",
            "color_name",
            "memory",
            "memory_volume",
            "size",
            "size_name",
            "attributes",
            "similar_products_sku",
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
    brand_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    brand_category = serializers.CharField(max_length=255, required=False, allow_blank=True)
    sku = serializers.CharField(max_length=100, required=False, allow_blank=True)
    color = serializers.CharField(max_length=120, required=False, allow_blank=True)
    memory = serializers.CharField(max_length=50, required=False, allow_blank=True)
    size = serializers.CharField(max_length=120, required=False, allow_blank=True)
    attributes = serializers.DictField(required=False, default=dict)
    similar_products_sku = serializers.CharField(required=False, allow_blank=True)
    wholesale_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=0, required=False, default=0)
    in_stock = serializers.BooleanField(required=False, default=False)

    def validate_sku(self, value):
        if value and ProductVariant.objects.filter(sku=value).exists():
            raise serializers.ValidationError("SKU already exists.")
        return value
