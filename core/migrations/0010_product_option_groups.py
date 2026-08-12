# Generated manually for Django 5.2

from django.db import migrations, models


def backfill_product_options(apps, schema_editor):
    ProductVariant = apps.get_model("core", "ProductVariant")

    for variant in ProductVariant.objects.select_related("product", "color", "memory", "size").iterator():
        product = variant.product
        if variant.color_id:
            product.colors.add(variant.color)
        if variant.memory_id:
            product.memories.add(variant.memory)
        if variant.size_id:
            product.sizes.add(variant.size)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_backfill_variant_options_from_attributes"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="memory_price",
            field=models.JSONField(blank=True, default=dict, verbose_name="Цена памяти"),
        ),
        migrations.AddField(
            model_name="product",
            name="colors",
            field=models.ManyToManyField(blank=True, related_name="products", to="core.productcolor", verbose_name="Цвет"),
        ),
        migrations.AddField(
            model_name="product",
            name="memories",
            field=models.ManyToManyField(blank=True, related_name="products", to="core.memory", verbose_name="Память"),
        ),
        migrations.AddField(
            model_name="product",
            name="sizes",
            field=models.ManyToManyField(blank=True, related_name="products", to="core.productsize", verbose_name="Размер"),
        ),
        migrations.RunPython(backfill_product_options, migrations.RunPython.noop),
    ]
