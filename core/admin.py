from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import ValidationError
from django.db import models as db_models
from django_json_widget.widgets import JSONEditorWidget

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


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Product — глобальный, не привязан к одному магазину напрямую.
    Видимость не ограничиваем по shop: карточку товара может создать любой
    залогиненный сотрудник, чтобы не плодить дубликаты одного и того же
    товара в разных магазинах.
    """

    list_display = ("name", "category", "created_at")
    search_fields = ("name", "category")


class ProductImageInline(admin.TabularInline):
    """
    Фото редактируются прямо на странице варианта товара — не нужно
    заходить в отдельный раздел, чтобы прикрепить картинку к SKU.
    """

    model = ProductImage
    extra = 1
    fields = ("image", "is_primary", "order")


class StockInline(ShopScopedAdminMixin, admin.TabularInline):
    """Наличие товара по магазинам прямо на странице SKU."""

    model = Stock
    extra = 1
    fields = ("shop", "wholesale_price", "in_stock", "updated_at")
    readonly_fields = ("updated_at",)


class ChannelPriceInline(ShopScopedAdminMixin, admin.TabularInline):
    """Цена канала, например MMarket/O!Market, прямо на странице SKU."""

    model = ChannelPrice
    extra = 1
    fields = ("shop", "channel", "price", "last_synced_at", "last_sync_error")
    readonly_fields = ("last_synced_at", "last_sync_error")


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "sku", "attributes", "is_active", "photo_count", "mmarket_prices")
    search_fields = ("sku", "product__name")
    list_filter = ("is_active",)
    inlines = [ProductImageInline, StockInline, ChannelPriceInline]
    formfield_overrides = {
        db_models.JSONField: {"widget": JSONEditorWidget},
    }

    def photo_count(self, obj):
        return obj.images.count()

    photo_count.short_description = "Фото"

    def mmarket_prices(self, obj):
        prices = obj.channel_prices.filter(channel__adapter_key="mmarket").select_related("channel")
        return ", ".join(f"{price.channel.name}: {price.price}" for price in prices) or "-"

    mmarket_prices.short_description = "M-Market цены"


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

    list_display = ("variant", "shop", "wholesale_price", "in_stock", "updated_at")
    list_editable = ("wholesale_price", "in_stock")
    list_filter = ("shop", "in_stock")
    search_fields = ("variant__sku", "variant__product__name")
    list_per_page = 1000


@admin.register(ChannelPrice)
class ChannelPriceAdmin(ShopScopedAdminMixin, admin.ModelAdmin):
    """Цена продажи по каждому каналу отдельно."""

    list_display = (
        "variant",
        "shop",
        "channel",
        "price",
        "updated_at",
        "last_synced_at",
        "last_sync_error",
    )
    list_editable = ("price",)
    list_filter = ("shop", "channel")
    search_fields = ("variant__sku", "variant__product__name")
    list_per_page = 1000
    actions = ["sync_selected_channels_to_marketplace"]

    @admin.action(description="Отправить выбранные каналы в маркетплейс")
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
