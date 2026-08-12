import secrets
import string

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Shop(models.Model):
    """Бизнес-единица: магазин 1/2/3. Изоляция данных строится вокруг этой модели."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ShopAPIKey(models.Model):
    """
    Ключ доступа к API для конкретного магазина (используется Apps Script).
    Ключ хранится в открытом виде намеренно — он не пароль пользователя,
    а секрет уровня "сервис-аккаунт", который можно отозвать в любой момент.
    """

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="api_keys")
    key = models.CharField(max_length=64, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"API key for {self.shop.name} ({'active' if self.is_active else 'revoked'})"


class ProductCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Product category"
        verbose_name_plural = "Product categories"

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class BrandCategory(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["brand__name", "name"]
        unique_together = [("brand", "name")]
        verbose_name = "Brand category"
        verbose_name_plural = "Brand categories"

    def __str__(self):
        return f"{self.brand.name} / {self.name}"


class Product(models.Model):
    """
    Глобальная карточка товара. Переиспользуется между магазинами:
    если магазин 1 и магазин 2 продают одну и ту же модель техники,
    это ОДНА запись Product, а не дубликаты.
    """

    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    category_ref = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    brand_name = models.CharField(max_length=255, blank=True)
    brand_ref = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    brand_category = models.CharField(
        max_length=255,
        blank=True,
        help_text="Категория внутри бренда: iPhone, MacBook, AirPods и т.п.",
    )
    brand_category_ref = models.ForeignKey(
        BrandCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.sync_catalog_refs()
        super().save(*args, **kwargs)

    def sync_catalog_refs(self):
        category_name = self.category.strip()
        brand_name = self.brand_name.strip()
        brand_category_name = self.brand_category.strip()

        if category_name:
            self.category = category_name
            self.category_ref, _ = ProductCategory.objects.get_or_create(name=category_name)
        else:
            self.category_ref = None

        if brand_name:
            self.brand_name = brand_name
            self.brand_ref, _ = Brand.objects.get_or_create(name=brand_name)
        else:
            self.brand_ref = None

        if self.brand_ref and brand_category_name:
            self.brand_category = brand_category_name
            self.brand_category_ref, _ = BrandCategory.objects.get_or_create(
                brand=self.brand_ref,
                name=brand_category_name,
            )
        else:
            self.brand_category_ref = None


class ProductVariant(models.Model):
    """
    Конкретная модификация товара (цвет/память/размер и т.п.).
    attributes хранится как JSON намеренно: разные категории техники
    имеют разные наборы атрибутов — жёсткие колонки под каждый атрибут
    не подходят при таком разнообразии категорий.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Уникальный артикул варианта. Если оставить пустым, сгенерируется SKU из 15 символов.",
    )
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text='Например: {"цвет": "чёрный", "память": "128GB"}',
    )
    similar_products_sku = models.TextField(
        blank=True,
        help_text="SKU похожих товаров для группировки. Можно через запятую или каждый SKU с новой строки.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["product__name", "sku"]

    def __str__(self):
        attrs = ", ".join(f"{k}: {v}" for k, v in self.attributes.items())
        return f"{self.product.name} ({attrs})" if attrs else f"{self.product.name} [{self.sku}]"

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = self.generate_unique_sku()
        super().save(*args, **kwargs)

    @classmethod
    def generate_unique_sku(cls):
        alphabet = string.ascii_uppercase + string.digits
        while True:
            sku = "".join(secrets.choice(alphabet) for _ in range(15))
            if not cls.objects.filter(sku=sku).exists():
                return sku

    @property
    def similar_products_sku_list(self):
        raw_skus = self.similar_products_sku.replace(",", "\n").splitlines()
        return [sku.strip() for sku in raw_skus if sku.strip()]


class ProductImage(models.Model):
    """
    Фото товара. Привязано к ProductVariant, а не к Product: разные цвета
    обычно выглядят по-разному на фото, и маркетплейсы ожидают фото именно
    под конкретный SKU (вариант), а не общую картинку на всю линейку.

    В базе данных хранится не сам файл, а путь к нему (стандартная практика,
    файл лежит на диске/в облачном хранилище отдельно от БД).

    ВАЖНО для продакшена: чтобы маркетплейсы могли забрать фото по URL,
    сервер должен быть публично доступен по HTTPS. На старте можно хранить
    файлы на диске сервера, при росте — вынести в S3-совместимое хранилище.
    """

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="product_images/%Y/%m/")
    is_primary = models.BooleanField(
        default=False, help_text="Главное фото — то, что уходит первым на маркетплейсы"
    )
    order = models.PositiveIntegerField(default=0, help_text="Порядок отображения, меньше = раньше")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"Photo for {self.variant} (#{self.order})"


class Channel(models.Model):
    """
    Канал сбыта конкретного магазина: маркетплейс, розница, сайт.
    Привязан к Shop, т.к. одноимённые маркетплейсы у разных магазинов —
    это разные аккаунты/API-подключения на стороне маркетплейса.
    """

    class ChannelType(models.TextChoices):
        MARKETPLACE = "marketplace", "Маркетплейс"
        RETAIL = "retail", "Розница"
        SITE = "site", "Сайт"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="channels")
    name = models.CharField(max_length=255)
    channel_type = models.CharField(max_length=20, choices=ChannelType.choices)
    adapter_key = models.CharField(
        max_length=100,
        blank=True,
        help_text="Идентификатор адаптера интеграции (см. EPIC 5), напр. 'mmarket'",
    )
    api_url = models.URLField(
        blank=True,
        help_text="URL API маркетплейса"
    )

    api_token = models.CharField(
        max_length=255,
        blank=True,
        help_text="Токен доступа"
    )

    branch_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="ID филиала маркетплейса"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("shop", "name")]

    def __str__(self):
        return f"{self.shop.name} / {self.name}"


class Stock(models.Model):
    """
    Оптовая цена и наличие товара в конкретном магазине — ОДНА запись
    на (variant, shop), не дублируется по каналам.
    """

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="stocks")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="stocks")

    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    quantity = models.PositiveIntegerField(
        default=0,
        help_text="Фактическое количество товара. В маркетплейсы уходит 0, если in_stock выключен.",
    )
    in_stock = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("variant", "shop")]
        verbose_name = "Stock"
        verbose_name_plural = "Stock"

    def __str__(self):
        return f"{self.variant} @ {self.shop} — {self.marketplace_quantity} pcs"

    @property
    def marketplace_quantity(self):
        return self.quantity if self.in_stock else 0


class ChannelPrice(models.Model):
    """
    Цена продажи на конкретном канале. Единственное поле, которое
    действительно различается между маркетплейсами для одного и того же
    товара в одном и том же магазине.
    """

    class SyncStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="channel_prices")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="channel_prices")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="channel_prices")

    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Сумма скидки для этого канала. Это не цена со скидкой, а размер скидки.",
    )
    sync_status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
    )

    updated_at = models.DateTimeField(auto_now=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True)

    class Meta:
        unique_together = [("variant", "shop", "channel")]
        verbose_name = "Channel price"
        verbose_name_plural = "Channel prices"

    def clean(self):
        if self.channel_id is None or self.shop_id is None:
            return
        if self.channel.shop_id != self.shop_id:
            raise ValidationError("Channel must belong to the same shop as this price record.")
        if self.price is not None and self.price < 0:
            raise ValidationError("Price cannot be negative.")

    def __str__(self):
        return f"{self.variant} @ {self.channel} = {self.price}"


class User(AbstractUser):
    """
    shop = None    -> супер-админ бизнеса (видит все магазины).
    shop = <Shop>  -> сотрудник конкретного магазина, видит только своё.
    """

    shop = models.ForeignKey(
        Shop,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
        help_text="Пусто = видит все магазины (супер-админ бизнеса)",
    )

    def __str__(self):
        return self.username
