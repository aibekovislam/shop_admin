import secrets

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


class Product(models.Model):
    """
    Глобальная карточка товара. Переиспользуется между магазинами:
    если магазин 1 и магазин 2 продают одну и ту же модель техники,
    это ОДНА запись Product, а не дубликаты.
    """

    name = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    """
    Конкретная модификация товара (цвет/память/размер и т.п.).
    attributes хранится как JSON намеренно: разные категории техники
    имеют разные наборы атрибутов — жёсткие колонки под каждый атрибут
    не подходят при таком разнообразии категорий.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=100, unique=True, help_text="Уникальный артикул варианта")
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text='Например: {"цвет": "чёрный", "память": "128GB"}',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["product__name", "sku"]

    def __str__(self):
        attrs = ", ".join(f"{k}: {v}" for k, v in self.attributes.items())
        return f"{self.product.name} ({attrs})" if attrs else f"{self.product.name} [{self.sku}]"


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
    in_stock = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("variant", "shop")]
        verbose_name = "Stock"
        verbose_name_plural = "Stock"

    def __str__(self):
        return f"{self.variant} @ {self.shop} — {'in stock' if self.in_stock else 'out of stock'}"


class ChannelPrice(models.Model):
    """
    Цена продажи на конкретном канале. Единственное поле, которое
    действительно различается между маркетплейсами для одного и того же
    товара в одном и том же магазине.
    """

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="channel_prices")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="channel_prices")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="channel_prices")

    price = models.DecimalField(max_digits=10, decimal_places=2)

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
