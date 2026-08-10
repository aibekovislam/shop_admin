from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import ValidationError
from django import forms
from django.utils.html import format_html

from .forms import KeyValueJSONWidget
from .marketplace.factory import get_marketplace_adapter
from .models import (
    Channel,
    ChannelPrice,
    Product,
    ProductImage,
    ProductVariant,
    Shop,
    ShopAPIKey,
    Stock,
    User,
)


class ShopScopedAdminMixin:
    """
    Общая логика: суперюзер видит всё, обычный пользователь — только
    записи своего магазина.
    """

    shop_lookup = "shop"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.shop_id is None:
            return qs.none()
        return qs.filter(**{self.shop_lookup: request.user.shop_id})

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser or obj is None:
            return super().has_change_permission(request, obj)
        return self._get_shop_id(obj) == request.user.shop_id

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def _get_shop_id(self, obj):
        attr = obj
        for part in self.shop_lookup.split("__"):
            attr = getattr(attr, part)
        return attr.id if hasattr(attr, "id") else attr


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    prepopulated_fields = {"slug": ("name",)}

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(id=request.user.shop_id) if request.user.shop_id else qs.none()


@admin.register(ShopAPIKey)
class ShopAPIKeyAdmin(ShopScopedAdminMixin, admin.ModelAdmin):
    list_display = ("shop", "key", "is_active", "created_at", "last_used_at")
    readonly_fields = ("key", "created_at", "last_used_at")


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"

    def clean_description(self):
        description = self.cleaned_data.get("description") or ""
        if len(description) < 50:
            raise ValidationError("Описание товара должно быть минимум 50 символов.")
        return description


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Product — глобальный, не привязан к одному магазину напрямую.
    Видимость не ограничиваем по shop: карточку товара может создать любой
    залогиненный сотрудник, чтобы не плодить дубликаты одного и того же
    товара в разных магазинах.
    """

    form = ProductAdminForm
    list_display = ("name", "category", "created_at")
    search_fields = ("name", "category")


class ProductImageInline(admin.TabularInline):
    """
    Фото редактируются прямо на странице варианта товара — не нужно
    заходить в отдельный раздел, чтобы прикрепить картинку к SKU.
    """

    model = ProductImage
    extra = 1
    fields = ("image", "image_preview", "is_primary", "order")
    readonly_fields = ("image_preview",)

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-width: 110px; max-height: 110px; object-fit: contain;" />',
                obj.image.url,
            )
        return "-"

    image_preview.short_description = "Превью"


class StockInline(ShopScopedAdminMixin, admin.TabularInline):
    """Наличие товара по магазинам прямо на странице SKU."""

    model = Stock
    extra = 1
    fields = ("shop", "wholesale_price", "quantity", "in_stock", "updated_at")
    readonly_fields = ("updated_at",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "shop" and not request.user.is_superuser and request.user.shop_id:
            kwargs["queryset"] = Shop.objects.filter(id=request.user.shop_id)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ChannelPriceInline(ShopScopedAdminMixin, admin.TabularInline):
    """Цена канала, например MMarket/O!Market, прямо на странице SKU."""

    model = ChannelPrice
    extra = 1
    fields = ("shop", "channel", "price", "last_synced_at", "last_sync_error")
    readonly_fields = ("last_synced_at", "last_sync_error")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser and request.user.shop_id:
            if db_field.name == "shop":
                kwargs["queryset"] = Shop.objects.filter(id=request.user.shop_id)
            if db_field.name == "channel":
                kwargs["queryset"] = Channel.objects.filter(shop_id=request.user.shop_id, is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ProductVariantAdminForm(forms.ModelForm):
    """
    Удобная форма SKU: можно создать или обновить связанную Product-карточку
    прямо с экрана варианта, как в старой товарной админке.
    """

    product = forms.ModelChoiceField(
        queryset=Product.objects.all(),
        required=False,
        label="Существующий продукт",
        help_text="Если выбрали существующий продукт, название/категорию/описание ниже можно оставить пустыми.",
    )
    product_name = forms.CharField(
        label="Название нового товара",
        required=False,
        max_length=255,
        help_text="Заполняйте для новой карточки или если хотите переименовать выбранный продукт.",
    )
    product_category = forms.CharField(
        label="Категория товара",
        required=False,
        max_length=255,
        help_text="Для выбранного существующего продукта пустое поле оставит старую категорию.",
    )
    product_description = forms.CharField(
        label="Описание товара",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Минимум 50 символов. Для выбранного существующего продукта пустое поле оставит старое описание.",
    )

    class Meta:
        model = ProductVariant
        fields = (
            "product",
            "product_name",
            "product_category",
            "product_description",
            "sku",
            "attributes",
            "is_active",
        )
        widgets = {
            "attributes": KeyValueJSONWidget,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.product_id:
            product = self.instance.product
            self.fields["product_name"].initial = product.name
            self.fields["product_category"].initial = product.category
            self.fields["product_description"].initial = product.description

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        product_name = cleaned_data.get("product_name")
        product_description = cleaned_data.get("product_description")
        attributes = cleaned_data.get("attributes") or {}
        if not product and not product_name:
            raise ValidationError("Укажите название товара или выберите существующий продукт.")

        should_validate_description = not product or bool(product_description)
        if should_validate_description and len(product_description or "") < 50:
            self.add_error("product_description", "Описание товара должно быть минимум 50 символов.")
        if "" in attributes:
            self.add_error("attributes", "У каждой характеристики должен быть заполнен ключ.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        product = self.cleaned_data.get("product") or getattr(instance, "product", None)

        if product is None:
            product = Product.objects.create(
                name=self.cleaned_data["product_name"],
                category=self.cleaned_data.get("product_category", ""),
                description=self.cleaned_data.get("product_description", ""),
            )
        else:
            product_name = self.cleaned_data.get("product_name")
            if product_name:
                product.name = product_name
                update_fields = ["name", "updated_at"]
                product_category = self.cleaned_data.get("product_category")
                product_description = self.cleaned_data.get("product_description")
                if product_category:
                    product.category = product_category
                    update_fields.append("category")
                if product_description:
                    product.description = product_description
                    update_fields.append("description")
                product.save(update_fields=update_fields)

        instance.product = product
        if commit:
            instance.save()
            self.save_m2m()
        return instance


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    form = ProductVariantAdminForm
    list_display = (
        "product",
        "sku",
        "product_category",
        "stock_summary",
        "channel_prices_summary",
        "is_active",
        "photo_count",
        "created_at",
        "first_image_preview",
    )
    search_fields = ("sku", "product__name", "product__category")
    readonly_fields = ("product_id_display", "first_image_preview", "created_at")
    list_filter = (
        "is_active",
        "product__category",
        "stocks__shop",
        "stocks__in_stock",
        "channel_prices__channel",
        "created_at",
    )
    ordering = ("-created_at", "-id")
    date_hierarchy = "created_at"
    inlines = [ProductImageInline, StockInline, ChannelPriceInline]
    fieldsets = (
        ("Информация о товаре", {
            "fields": ("product_id_display", "product", "product_name", "product_category", "product_description"),
        }),
        ("SKU и характеристики", {
            "fields": ("sku", "attributes", "is_active", "created_at"),
            "description": (
                "Для M-Market обязательны ключи характеристик: Тип, Производители, Модель, Цвет. "
                "Можно писать цвет/модель/производитель маленькими буквами — при отправке в M-Market ключи нормализуются. "
                "Для Bakai Market бренд берётся из ключей: Бренд, brand, Производитель, Производители."
            ),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        if obj:
            fieldsets.append(("Превью", {"fields": ("first_image_preview",)}))
        return fieldsets

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("product")
            .prefetch_related("images", "stocks__shop", "channel_prices__channel")
        )

    def product_id_display(self, obj):
        if obj and obj.pk:
            return format_html("<strong>ID SKU: {}</strong>", obj.pk)
        return "Новый SKU"

    product_id_display.short_description = "ID"

    def product_category(self, obj):
        return obj.product.category or "-"

    product_category.short_description = "Категория"

    def photo_count(self, obj):
        return obj.images.count()

    photo_count.short_description = "Фото"

    def stock_summary(self, obj):
        stocks = obj.stocks.select_related("shop")
        return ", ".join(
            f"{stock.shop.name}: {stock.marketplace_quantity}"
            for stock in stocks
        ) or "-"

    stock_summary.short_description = "Остатки"

    def channel_prices_summary(self, obj):
        prices = obj.channel_prices.select_related("channel")
        return ", ".join(f"{price.channel.name}: {price.price}" for price in prices) or "-"

    channel_prices_summary.short_description = "Цены каналов"

    def first_image_preview(self, obj):
        if not obj or not obj.pk:
            return "-"
        image = obj.images.first()
        if not image:
            return "-"
        return format_html(
            '<img src="{}" style="max-width: 150px; max-height: 150px; object-fit: contain;" />',
            image.image.url,
        )

    first_image_preview.short_description = "Превью"


@admin.register(Channel)
class ChannelAdmin(ShopScopedAdminMixin, admin.ModelAdmin):
    list_display = ("shop", "name", "channel_type", "adapter_key", "api_url", "branch_id", "is_active")
    list_filter = ("channel_type", "is_active")
    actions = ["sync_marketplace_products"]

    @admin.action(description="Отправить товары в маркетплейс")
    def sync_marketplace_products(self, request, queryset):
        for channel in queryset:
            if not channel.adapter_key:
                self.message_user(
                    request,
                    f"{channel}: пропущен, adapter_key не заполнен.",
                    level=messages.WARNING,
                )
                continue
            try:
                result = get_marketplace_adapter(channel).push_products()
            except ValidationError as exc:
                self.message_user(request, f"{channel}: {exc}", level=messages.ERROR)
            except Exception as exc:  # noqa: BLE001
                self.message_user(request, f"{channel}: ошибка M-Market: {exc}", level=messages.ERROR)
            else:
                self.message_user(request, f"{channel}: выгрузка отправлена. Ответ: {result}")


@admin.register(Stock)
class StockAdmin(ShopScopedAdminMixin, admin.ModelAdmin):
    """
    Одна строка на товар в магазине — наличие и оптовая цена, единые для
    всех каналов. Табличное редактирование (list_editable) с одной кнопкой
    Save на все изменённые строки.
    """

    list_display = ("variant", "shop", "wholesale_price", "quantity", "in_stock", "updated_at")
    list_editable = ("wholesale_price", "quantity", "in_stock")
    list_filter = ("shop", "in_stock")
    search_fields = ("variant__sku", "variant__product__name")
    list_per_page = 1000


@admin.register(ChannelPrice)
class ChannelPriceAdmin(ShopScopedAdminMixin, admin.ModelAdmin):
    """Цена продажи по каждому каналу отдельно."""

    list_display = (
        "product_name",
        "variant_sku",
        "channel",
        "price",
        "stock_quantity",
        "updated_at",
        "last_synced_at",
        "last_sync_error",
    )
    list_editable = ("price",)
    list_filter = (
        "shop",
        "channel",
        "channel__adapter_key",
        "variant__is_active",
        "variant__product__category",
        "last_synced_at",
    )
    search_fields = ("variant__sku", "variant__product__name", "variant__product__category", "channel__name")
    ordering = ("-updated_at", "-id")
    date_hierarchy = "updated_at"
    list_per_page = 1000
    actions = ["sync_selected_channels_to_marketplace"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("variant__product", "shop", "channel")
            .prefetch_related("variant__stocks")
        )

    def product_name(self, obj):
        return obj.variant.product.name

    product_name.short_description = "Товар"
    product_name.admin_order_field = "variant__product__name"

    def variant_sku(self, obj):
        return obj.variant.sku

    variant_sku.short_description = "SKU"
    variant_sku.admin_order_field = "variant__sku"

    def stock_quantity(self, obj):
        stock = self._get_stock_for_price(obj)
        return stock.marketplace_quantity if stock else 0

    stock_quantity.short_description = "Кол-во в маркет"

    def _get_stock_for_price(self, obj):
        for stock in obj.variant.stocks.all():
            if stock.shop_id == obj.shop_id:
                return stock
        return None

    @admin.action(description="Отправить весь канал выбранных цен в маркетплейс")
    def sync_selected_channels_to_marketplace(self, request, queryset):
        channels = Channel.objects.filter(
            id__in=queryset.values_list("channel_id", flat=True),
        ).exclude(adapter_key="")
        if not channels.exists():
            self.message_user(
                request,
                "Среди выбранных цен нет канала с заполненным adapter_key.",
                level=messages.WARNING,
            )
            return

        for channel in channels:
            try:
                result = get_marketplace_adapter(channel).push_products()
            except ValidationError as exc:
                queryset.filter(channel=channel).update(last_sync_error=str(exc))
                self.message_user(request, f"{channel}: {exc}", level=messages.ERROR)
            except Exception as exc:  # noqa: BLE001
                queryset.filter(channel=channel).update(last_sync_error=str(exc))
                self.message_user(request, f"{channel}: ошибка M-Market: {exc}", level=messages.ERROR)
            else:
                self.message_user(request, f"{channel}: выгрузка отправлена. Ответ: {result}")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("Shop", {"fields": ("shop",)}),)
    list_display = ("username", "email", "shop", "is_staff", "is_superuser")
    list_filter = DjangoUserAdmin.list_filter + ("shop",)
