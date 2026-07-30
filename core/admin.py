from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db import models as db_models
from django_json_widget.widgets import JSONEditorWidget

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


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ("product", "sku", "attributes", "is_active", "photo_count")
    search_fields = ("sku", "product__name")
    list_filter = ("is_active",)
    inlines = [ProductImageInline]
    formfield_overrides = {
        db_models.JSONField: {"widget": JSONEditorWidget},
    }

    def photo_count(self, obj):
        return obj.images.count()

    photo_count.short_description = "Фото"


@admin.register(Channel)
class ChannelAdmin(ShopScopedAdminMixin, admin.ModelAdmin):
    list_display = ("shop", "name", "channel_type", "adapter_key", "is_active")
    list_filter = ("channel_type", "is_active")


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

    list_display = ("variant", "shop", "channel", "price", "updated_at", "last_synced_at")
    list_editable = ("price",)
    list_filter = ("shop", "channel")
    search_fields = ("variant__sku", "variant__product__name")
    list_per_page = 1000


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("Shop", {"fields": ("shop",)}),)
    list_display = ("username", "email", "shop", "is_staff", "is_superuser")
    list_filter = DjangoUserAdmin.list_filter + ("shop",)
