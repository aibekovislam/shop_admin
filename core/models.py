import secrets
import string

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Shop(models.Model):
    """Бизнес-единица: магазин 1/2/3. Изоляция данных строится вокруг этой модели."""

    name = models.CharField("Название", max_length=255)
    slug = models.SlugField("Slug", max_length=255, unique=True)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Магазин"
        verbose_name_plural = "Магазины"

    def __str__(self):
        return self.name


class ShopAPIKey(models.Model):
    """
    Ключ доступа к API для конкретного магазина (используется Apps Script).
    Ключ хранится в открытом виде намеренно — он не пароль пользователя,
    а секрет уровня "сервис-аккаунт", который можно отозвать в любой момент.
    """

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="api_keys", verbose_name="Магазин")
    key = models.CharField("Ключ", max_length=64, unique=True, editable=False)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    last_used_at = models.DateTimeField("Последнее использование", null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        status = "активен" if self.is_active else "отозван"
        return f"API ключ для {self.shop.name} ({status})"

    class Meta:
        verbose_name = "API ключ магазина"
        verbose_name_plural = "API ключи магазинов"


class ProductCategory(models.Model):
    name = models.CharField("Название", max_length=255, unique=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Категория товара"
        verbose_name_plural = "Категории товаров"

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField("Название", max_length=255, unique=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Бренд"
        verbose_name_plural = "Бренды"

    def __str__(self):
        return self.name


class BrandCategory(models.Model):
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="categories", verbose_name="Бренд")
    name = models.CharField("Название", max_length=255)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        ordering = ["brand__name", "name"]
        unique_together = [("brand", "name")]
        verbose_name = "Категория бренда"
        verbose_name_plural = "Категории брендов"

    def __str__(self):
        return f"{self.brand.name} / {self.name}"


class ProductColor(models.Model):
    name = models.CharField("Название", max_length=120, unique=True)
    hash_code = models.CharField("HEX-код цвета", max_length=25, default="#000000")
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Цвет товара"
        verbose_name_plural = "Цвета товаров"

    def __str__(self):
        return f"{self.name} ({self.hash_code})" if self.hash_code else self.name


class Memory(models.Model):
    volume = models.CharField("Объём памяти", max_length=50, unique=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ["volume"]
        verbose_name = "Память"
        verbose_name_plural = "Память"

    def __str__(self):
        return self.volume


class ProductSize(models.Model):
    name = models.CharField("Размер", max_length=120, unique=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Размер"
        verbose_name_plural = "Размеры"

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Глобальная карточка товара. Переиспользуется между магазинами:
    если магазин 1 и магазин 2 продают одну и ту же модель техники,
    это ОДНА запись Product, а не дубликаты.
    """

    name = models.CharField("Название", max_length=255)
    category = models.CharField("Категория товара", max_length=255, blank=True)
    category_ref = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Категория из справочника",
    )
    brand_name = models.CharField("Бренд товара", max_length=255, blank=True)
    brand_ref = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="Бренд из справочника",
    )
    brand_category = models.CharField(
        "Категория бренда",
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
        verbose_name="Категория бренда из справочника",
    )
    description = models.TextField("Описание", blank=True)
    memory_price = models.JSONField("Цена памяти", default=dict, blank=True)
    colors = models.ManyToManyField(ProductColor, related_name="products", blank=True, verbose_name="Цвет")
    memories = models.ManyToManyField(Memory, related_name="products", blank=True, verbose_name="Память")
    sizes = models.ManyToManyField(ProductSize, related_name="products", blank=True, verbose_name="Размер")
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Товар"
        verbose_name_plural = "Товары"

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

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants", verbose_name="Товар")
    color = models.ForeignKey(
        ProductColor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="variants",
        verbose_name="Цвет",
    )
    memory = models.ForeignKey(
        Memory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="variants",
        verbose_name="Память",
    )
    size = models.ForeignKey(
        ProductSize,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="variants",
        verbose_name="Размер",
    )
    sku = models.CharField(
        "SKU",
        max_length=100,
        unique=True,
        blank=True,
        help_text="Уникальный артикул варианта. Если оставить пустым, сгенерируется SKU из 15 символов.",
    )
    attributes = models.JSONField(
        "Характеристики",
        default=dict,
        blank=True,
        help_text='Например: {"цвет": "чёрный", "память": "128GB"}',
    )
    similar_products_sku = models.TextField(
        "Похожие SKU",
        blank=True,
        help_text="SKU похожих товаров для группировки. Можно через запятую или каждый SKU с новой строки.",
    )
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        ordering = ["product__name", "sku"]
        verbose_name = "Вариант товара"
        verbose_name_plural = "Варианты товаров"

    def __str__(self):
        option_attrs = self.option_attributes()
        attrs = ", ".join(f"{k}: {v}" for k, v in {**option_attrs, **self.attributes}.items())
        return f"{self.product.name} ({attrs})" if attrs else f"{self.product.name} [{self.sku}]"

    def save(self, *args, **kwargs):
        if not self.sku:
            self.sku = self.generate_unique_sku()
        self.sync_option_attributes()
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

    def option_attributes(self):
        attrs = {}
        if self.color_id:
            attrs["Цвет"] = self.color.name
        if self.memory_id:
            attrs["Память"] = self.memory.volume
        if self.size_id:
            attrs["Размер"] = self.size.name
        return attrs

    def sync_option_attributes(self):
        attrs = dict(self.attributes or {})
        for key, value in self.option_attributes().items():
            attrs[key] = value
        self.attributes = attrs


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

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name="images",
        verbose_name="Вариант товара",
    )
    image = models.ImageField("Фото", upload_to="product_images/%Y/%m/")
    color = models.ForeignKey(
        ProductColor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="images",
        verbose_name="Цвет",
        help_text="Если фото относится к конкретному цвету, выберите цвет.",
    )
    is_primary = models.BooleanField(
        "Главное фото",
        default=False, help_text="Главное фото — то, что уходит первым на маркетплейсы"
    )
    order = models.PositiveIntegerField("Порядок", default=0, help_text="Порядок отображения, меньше = раньше")
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "Фото товара"
        verbose_name_plural = "Фото товаров"

    def __str__(self):
        return f"Фото для {self.variant}"


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

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="channels", verbose_name="Магазин")
    name = models.CharField("Название", max_length=255)
    channel_type = models.CharField("Тип канала", max_length=20, choices=ChannelType.choices)
    adapter_key = models.CharField(
        "Ключ адаптера",
        max_length=100,
        blank=True,
        help_text="Идентификатор адаптера интеграции (см. EPIC 5), напр. 'mmarket'",
    )
    api_url = models.URLField(
        "API URL",
        blank=True,
        help_text="URL API маркетплейса"
    )

    api_token = models.CharField(
        "API токен",
        max_length=255,
        blank=True,
        help_text="Токен доступа"
    )

    branch_id = models.PositiveIntegerField(
        "ID филиала",
        null=True,
        blank=True,
        help_text="ID филиала маркетплейса"
    )
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        unique_together = [("shop", "name")]
        verbose_name = "Канал продаж"
        verbose_name_plural = "Каналы продаж"

    def __str__(self):
        return f"{self.shop.name} / {self.name}"


class Stock(models.Model):
    """
    Оптовая цена и наличие товара в конкретном магазине — ОДНА запись
    на (variant, shop), не дублируется по каналам.
    """

    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="stocks", verbose_name="Вариант")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="stocks", verbose_name="Магазин")

    wholesale_price = models.DecimalField("Оптовая цена", max_digits=10, decimal_places=2, null=True, blank=True)
    quantity = models.PositiveIntegerField(
        "Количество",
        default=0,
        help_text="Фактическое количество товара. В маркетплейсы уходит 0, если in_stock выключен.",
    )
    in_stock = models.BooleanField("В наличии", default=False)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        unique_together = [("variant", "shop")]
        verbose_name = "Остаток"
        verbose_name_plural = "Остатки"

    def __str__(self):
        return f"{self.variant} @ {self.shop} — {self.marketplace_quantity} шт."

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
        PENDING = "pending", "Ожидает"
        SUCCESS = "success", "Успешно"
        WARNING = "warning", "Предупреждение"
        ERROR = "error", "Ошибка"

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name="channel_prices",
        verbose_name="Вариант",
    )
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="channel_prices", verbose_name="Магазин")
    channel = models.ForeignKey(
        Channel,
        on_delete=models.CASCADE,
        related_name="channel_prices",
        verbose_name="Канал",
    )

    price = models.DecimalField("Цена", max_digits=10, decimal_places=2)
    discount_amount = models.DecimalField(
        "Скидка",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Сумма скидки для этого канала. Это не цена со скидкой, а размер скидки.",
    )
    sync_status = models.CharField(
        "Статус синка",
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
    )

    updated_at = models.DateTimeField("Обновлено", auto_now=True)
    last_synced_at = models.DateTimeField("Последняя отправка", null=True, blank=True)
    last_sync_error = models.TextField("Ошибка отправки", blank=True)

    class Meta:
        unique_together = [("variant", "shop", "channel")]
        verbose_name = "Цена канала"
        verbose_name_plural = "Цены каналов"

    def clean(self):
        if self.channel_id is None or self.shop_id is None:
            return
        if self.channel.shop_id != self.shop_id:
            raise ValidationError("Канал должен принадлежать тому же магазину, что и запись цены.")
        if self.price is not None and self.price < 0:
            raise ValidationError("Цена не может быть отрицательной.")

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
        verbose_name="Магазин",
        help_text="Пусто = видит все магазины (супер-админ бизнеса)",
    )

    def __str__(self):
        return self.username

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
