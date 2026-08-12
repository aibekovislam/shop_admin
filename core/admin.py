from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.widgets import FilteredSelectMultiple, RelatedFieldWidgetWrapper
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import ValidationError
from django import forms
from django.utils.html import format_html, format_html_join

from .forms import KeyValueJSONWidget
from .marketplace.factory import get_marketplace_adapter
from .models import (
    Brand,
    BrandCategory,
    Channel,
    ChannelPrice,
    Memory,
    Product,
    ProductCategory,
    ProductColor,
    ProductImage,
    ProductSize,
    ProductVariant,
    Shop,
    ShopAPIKey,
    Stock,
    User,
)


admin.site.site_header = "Админка магазина"
admin.site.site_title = "Админка магазина"
admin.site.index_title = "Управление каталогом"


def model_name_values(model):
    return model.objects.order_by("name").values_list("name", flat=True).distinct()


class HexColorInput(forms.TextInput):
    input_type = "color"


class DatalistTextInput(forms.TextInput):
    def __init__(self, choices=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.choices = list(choices or [])

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs.copy() if attrs else {}
        datalist_id = f"{attrs.get('id', f'id_{name}')}_choices"
        attrs["list"] = datalist_id
        input_html = super().render(name, value, attrs, renderer)
        options_html = format_html_join(
            "",
            '<option value="{}"></option>',
            ((choice,) for choice in self.choices),
        )
        return format_html("{}<datalist id=\"{}\">{}</datalist>", input_html, datalist_id, options_html)


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


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


class BrandCategoryInline(admin.TabularInline):
    model = BrandCategory
    extra = 1
    fields = ("name", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "brand_categories", "created_at")
    search_fields = ("name",)
    inlines = [BrandCategoryInline]

    def brand_categories(self, obj):
        return ", ".join(obj.categories.values_list("name", flat=True)) or "-"

    brand_categories.short_description = "Категории бренда"


@admin.register(BrandCategory)
class BrandCategoryAdmin(admin.ModelAdmin):
    list_display = ("brand", "name", "created_at")
    list_filter = ("brand",)
    search_fields = ("name", "brand__name")


@admin.register(ProductColor)
class ProductColorAdmin(admin.ModelAdmin):
    class ProductColorAdminForm(forms.ModelForm):
        class Meta:
            model = ProductColor
            fields = "__all__"
            widgets = {
                "hash_code": HexColorInput,
            }

        def clean_hash_code(self):
            value = (self.cleaned_data.get("hash_code") or "#000000").strip()
            if not value.startswith("#"):
                value = f"#{value}"
            if len(value) != 7:
                raise ValidationError("HEX-код должен быть в формате #000000.")
            return value.upper()

    form = ProductColorAdminForm
    list_display = ("name", "hash_code", "color_preview", "created_at")
    search_fields = ("name", "hash_code")

    def color_preview(self, obj):
        return format_html(
            '<span style="display:inline-block;width:22px;height:22px;border:1px solid #999;background:{};"></span>',
            obj.hash_code,
        )

    color_preview.short_description = "Цвет"


@admin.register(Memory)
class MemoryAdmin(admin.ModelAdmin):
    list_display = ("volume", "created_at")
    search_fields = ("volume",)


@admin.register(ProductSize)
class ProductSizeAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"
        widgets = {
            "memory_price": KeyValueJSONWidget,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].widget = DatalistTextInput(choices=model_name_values(ProductCategory))
        self.fields["brand_name"].widget = DatalistTextInput(choices=model_name_values(Brand))
        self.fields["brand_category"].widget = DatalistTextInput(choices=model_name_values(BrandCategory))

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
    list_display = ("name", "category", "brand_name", "brand_category", "created_at")
    search_fields = ("name", "category", "brand_name", "brand_category")
    readonly_fields = ("category_ref", "brand_ref", "brand_category_ref")
    filter_horizontal = ("colors", "memories", "sizes")
    fieldsets = (
        ("Название и описание", {
            "fields": ("name", "category", "brand_name", "brand_category", "description"),
        }),
        ("Характеристики и опции", {
            "fields": ("memory_price", "colors", "memories", "sizes"),
        }),
        ("Справочники", {
            "fields": ("category_ref", "brand_ref", "brand_category_ref"),
        }),
    )


class ProductImageInline(admin.TabularInline):
    """
    Фото редактируются прямо на странице варианта товара — не нужно
    заходить в отдельный раздел, чтобы прикрепить картинку к SKU.
    """

    model = ProductImage
    extra = 1
    fields = ("image", "image_preview")
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
    fields = ("shop", "channel", "price", "discount_amount", "sync_status", "last_synced_at", "last_sync_error")
    readonly_fields = ("sync_status", "last_synced_at", "last_sync_error")

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
    product_brand_name = forms.CharField(
        label="Бренд товара",
        required=False,
        max_length=255,
        help_text="Например: Apple, Samsung, Xiaomi.",
    )
    product_brand_category = forms.CharField(
        label="Категория бренда",
        required=False,
        max_length=255,
        help_text="Например: iPhone, MacBook, AirPods.",
    )
    product_description = forms.CharField(
        label="Описание товара",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Минимум 50 символов. Для выбранного существующего продукта пустое поле оставит старое описание.",
    )
    product_memory_price = forms.JSONField(
        label="Цена памяти",
        required=False,
        widget=KeyValueJSONWidget,
        help_text="Как в старой админке: ключ — память, значение — цена.",
    )
    product_colors = forms.ModelMultipleChoiceField(
        label="Цвет",
        queryset=ProductColor.objects.none(),
        required=False,
        widget=FilteredSelectMultiple("Цвет", is_stacked=False),
        help_text="Выберите цвета товара. Первый выбранный цвет уйдёт в M-Market для этого SKU.",
    )
    product_memories = forms.ModelMultipleChoiceField(
        label="Память",
        queryset=Memory.objects.none(),
        required=False,
        widget=FilteredSelectMultiple("Память", is_stacked=False),
        help_text="Выберите варианты памяти. Первая выбранная память уйдёт в M-Market для этого SKU.",
    )
    product_sizes = forms.ModelMultipleChoiceField(
        label="Размер",
        queryset=ProductSize.objects.none(),
        required=False,
        widget=FilteredSelectMultiple("Размер", is_stacked=False),
        help_text="Выберите размеры товара, если они нужны.",
    )
    sync_after_save = forms.BooleanField(
        label="Отправить в маркетплейсы после сохранения",
        required=False,
        help_text="После сохранения отправит товары по заполненным ценам каналов этого SKU.",
    )
    similar_variants = forms.ModelMultipleChoiceField(
        label="Похожие товары",
        queryset=ProductVariant.objects.none(),
        required=False,
        widget=FilteredSelectMultiple("похожие товары", is_stacked=False),
        help_text="Выберите варианты, которые должны группироваться вместе на маркетплейсе.",
    )

    class Meta:
        model = ProductVariant
        fields = (
            "product",
            "product_name",
            "product_category",
            "product_brand_name",
            "product_brand_category",
            "product_description",
            "product_memory_price",
            "product_colors",
            "product_memories",
            "product_sizes",
            "sku",
            "attributes",
            "similar_variants",
            "is_active",
            "sync_after_save",
        )
        widgets = {
            "attributes": KeyValueJSONWidget,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product_category"].widget = DatalistTextInput(choices=model_name_values(ProductCategory))
        self.fields["product_brand_name"].widget = DatalistTextInput(choices=model_name_values(Brand))
        self.fields["product_brand_category"].widget = DatalistTextInput(
            choices=model_name_values(BrandCategory)
        )
        self.fields["product_colors"].queryset = ProductColor.objects.order_by("name")
        self.fields["product_memories"].queryset = Memory.objects.order_by("volume")
        self.fields["product_sizes"].queryset = ProductSize.objects.order_by("name")
        self.wrap_product_option_widgets()
        similar_queryset = ProductVariant.objects.select_related("product").order_by("product__name", "sku")
        if self.instance and self.instance.pk:
            similar_queryset = similar_queryset.exclude(pk=self.instance.pk)
        self.fields["similar_variants"].queryset = similar_queryset
        if self.instance and self.instance.pk and self.instance.product_id:
            product = self.instance.product
            self.fields["product_name"].initial = product.name
            self.fields["product_category"].initial = product.category
            self.fields["product_brand_name"].initial = product.brand_name
            self.fields["product_brand_category"].initial = product.brand_category
            self.fields["product_description"].initial = product.description
            self.fields["product_memory_price"].initial = product.memory_price or {}
            self.fields["product_colors"].initial = product.colors.all()
            self.fields["product_memories"].initial = product.memories.all()
            self.fields["product_sizes"].initial = product.sizes.all()
            self.fields["similar_variants"].initial = ProductVariant.objects.filter(
                sku__in=self.instance.similar_products_sku_list,
            )

    def wrap_product_option_widgets(self):
        option_fields = {
            "product_colors": "colors",
            "product_memories": "memories",
            "product_sizes": "sizes",
        }
        for form_field_name, model_field_name in option_fields.items():
            self.fields[form_field_name].widget = RelatedFieldWidgetWrapper(
                self.fields[form_field_name].widget,
                Product._meta.get_field(model_field_name).remote_field,
                admin.site,
                can_add_related=True,
                can_change_related=True,
                can_delete_related=False,
                can_view_related=True,
            )

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
        created_product = product is None

        if product is None:
            product = Product.objects.create(
                name=self.cleaned_data["product_name"],
                category=self.cleaned_data.get("product_category", ""),
                brand_name=self.cleaned_data.get("product_brand_name", ""),
                brand_category=self.cleaned_data.get("product_brand_category", ""),
                description=self.cleaned_data.get("product_description", ""),
                memory_price=self.cleaned_data.get("product_memory_price") or {},
            )
        else:
            product_name = self.cleaned_data.get("product_name")
            product_brand_name = self.cleaned_data.get("product_brand_name")
            product_brand_category = self.cleaned_data.get("product_brand_category")
            product_category = self.cleaned_data.get("product_category")
            product_description = self.cleaned_data.get("product_description")
            product_memory_price = self.cleaned_data.get("product_memory_price")
            if (
                product_name
                or product_category
                or product_brand_name
                or product_brand_category
                or product_description
                or product_memory_price is not None
            ):
                update_fields = ["updated_at"]
                if product_name:
                    product.name = product_name
                    update_fields.append("name")
                if product_category:
                    product.category = product_category
                    update_fields.append("category")
                if product_brand_name:
                    product.brand_name = product_brand_name
                    update_fields.append("brand_name")
                if product_brand_category:
                    product.brand_category = product_brand_category
                    update_fields.append("brand_category")
                if product_description:
                    product.description = product_description
                    update_fields.append("description")
                if product_memory_price is not None:
                    product.memory_price = product_memory_price or {}
                    update_fields.append("memory_price")
                product.save(update_fields=update_fields)

        self.sync_product_options(product, created_product=created_product)
        instance.product = product
        product_colors = list(self.cleaned_data.get("product_colors") or product.colors.all())
        product_memories = list(self.cleaned_data.get("product_memories") or product.memories.all())
        product_sizes = list(self.cleaned_data.get("product_sizes") or product.sizes.all())
        instance.color = product_colors[0] if product_colors else None
        instance.memory = product_memories[0] if product_memories else None
        instance.size = product_sizes[0] if product_sizes else None
        instance.similar_products_sku = "\n".join(
            variant.sku for variant in self.cleaned_data.get("similar_variants", [])
        )
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    def sync_product_options(self, product, created_product=False):
        should_replace_options = created_product or bool(self.instance and self.instance.pk)
        product_colors = self.cleaned_data.get("product_colors")
        product_memories = self.cleaned_data.get("product_memories")
        product_sizes = self.cleaned_data.get("product_sizes")

        if should_replace_options or product_colors:
            product.colors.set(product_colors or [])
        if should_replace_options or product_memories:
            product.memories.set(product_memories or [])
        if should_replace_options or product_sizes:
            product.sizes.set(product_sizes or [])


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    form = ProductVariantAdminForm
    list_display = (
        "product",
        "sku",
        "variant_color",
        "variant_memory",
        "variant_size",
        "product_category",
        "stock_summary",
        "channel_prices_summary",
        "sync_status_summary",
        "is_active",
        "photo_count",
        "created_at",
        "first_image_preview",
    )
    search_fields = ("sku", "product__name", "product__category", "color__name", "memory__volume", "size__name")
    readonly_fields = ("product_id_display", "first_image_preview", "created_at")
    list_filter = (
        "is_active",
        "color",
        "memory",
        "size",
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
            "fields": (
                "product_id_display",
                "product",
                "product_name",
                "product_category",
                "product_brand_name",
                "product_brand_category",
                "product_description",
            ),
        }),
        ("SKU и характеристики", {
            "fields": (
                "product_memory_price",
                "product_colors",
                "product_memories",
                "product_sizes",
                "sku",
                "attributes",
                "similar_variants",
                "is_active",
                "sync_after_save",
                "created_at",
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
            .select_related("product", "color", "memory", "size")
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

    def variant_color(self, obj):
        return obj.color.name if obj.color_id else "-"

    variant_color.short_description = "Цвет"
    variant_color.admin_order_field = "color__name"

    def variant_memory(self, obj):
        return obj.memory.volume if obj.memory_id else "-"

    variant_memory.short_description = "Память"
    variant_memory.admin_order_field = "memory__volume"

    def variant_size(self, obj):
        return obj.size.name if obj.size_id else "-"

    variant_size.short_description = "Размер"
    variant_size.admin_order_field = "size__name"

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
        return ", ".join(
            f"{price.channel.name}: {price.price}"
            + (f" (-{price.discount_amount})" if price.discount_amount else "")
            for price in prices
        ) or "-"

    channel_prices_summary.short_description = "Цены каналов"

    def sync_status_summary(self, obj):
        prices = obj.channel_prices.select_related("channel")
        return ", ".join(f"{price.channel.name}: {price.get_sync_status_display()}" for price in prices) or "-"

    sync_status_summary.short_description = "Статус синка"

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

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if form.cleaned_data.get("sync_after_save"):
            self.sync_variant_channel_prices(request, form.instance)

    def sync_variant_channel_prices(self, request, variant):
        prices = (
            variant.channel_prices.select_related("channel")
            .filter(channel__adapter_key__gt="")
        )
        if not prices.exists():
            self.message_user(
                request,
                f"{variant.sku}: нет цен каналов с adapter_key для отправки.",
                level=messages.WARNING,
            )
            return

        for channel in Channel.objects.filter(id__in=prices.values_list("channel_id", flat=True)):
            selected_price_ids = list(prices.filter(channel=channel).values_list("id", flat=True))
            try:
                result = get_marketplace_adapter(channel).push_products(channel_price_ids=selected_price_ids)
            except ValidationError as exc:
                prices.filter(channel=channel).update(
                    sync_status=ChannelPrice.SyncStatus.ERROR,
                    last_sync_error=str(exc),
                )
                self.message_user(request, f"{channel}: {exc}", level=messages.ERROR)
            except Exception as exc:  # noqa: BLE001
                prices.filter(channel=channel).update(
                    sync_status=ChannelPrice.SyncStatus.ERROR,
                    last_sync_error=str(exc),
                )
                self.message_user(request, f"{channel}: ошибка маркетплейса: {exc}", level=messages.ERROR)
            else:
                self.message_user(request, f"{channel}: выгрузка отправлена. Ответ: {result}")


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
        "discount_amount",
        "stock_quantity",
        "sync_status",
    )
    list_editable = ("price", "discount_amount")
    list_filter = (
        "shop",
        "channel",
        "channel__adapter_key",
        "sync_status",
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

    @admin.action(description="Отправить выбранные товары в маркетплейс")
    def sync_selected_channels_to_marketplace(self, request, queryset):
        skipped_prices = queryset.filter(channel__adapter_key="")
        if skipped_prices.exists():
            skipped_prices.update(
                sync_status=ChannelPrice.SyncStatus.WARNING,
                last_sync_error="У канала не заполнен adapter_key.",
            )
            self.message_user(
                request,
                "Часть выбранных цен пропущена: у канала не заполнен adapter_key.",
                level=messages.WARNING,
            )

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
            selected_price_ids = list(queryset.filter(channel=channel).values_list("id", flat=True))
            try:
                result = get_marketplace_adapter(channel).push_products(channel_price_ids=selected_price_ids)
            except ValidationError as exc:
                queryset.filter(channel=channel).update(
                    sync_status=ChannelPrice.SyncStatus.ERROR,
                    last_sync_error=str(exc),
                )
                self.message_user(request, f"{channel}: {exc}", level=messages.ERROR)
            except Exception as exc:  # noqa: BLE001
                queryset.filter(channel=channel).update(
                    sync_status=ChannelPrice.SyncStatus.ERROR,
                    last_sync_error=str(exc),
                )
                self.message_user(request, f"{channel}: ошибка маркетплейса: {exc}", level=messages.ERROR)
            else:
                self.message_user(request, f"{channel}: выгрузка отправлена. Ответ: {result}")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (("Shop", {"fields": ("shop",)}),)
    list_display = ("username", "email", "shop", "is_staff", "is_superuser")
    list_filter = DjangoUserAdmin.list_filter + ("shop",)
