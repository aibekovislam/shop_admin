# Generated manually for Django 5.2

from django.db import migrations


def get_attr(attributes, aliases):
    if not isinstance(attributes, dict):
        return ""
    alias_map = {alias.lower(): alias for alias in aliases}
    for key, value in attributes.items():
        if str(key).strip().lower() in alias_map and value:
            return str(value).strip()
    return ""


def backfill_variant_options(apps, schema_editor):
    ProductVariant = apps.get_model("core", "ProductVariant")
    ProductColor = apps.get_model("core", "ProductColor")
    Memory = apps.get_model("core", "Memory")
    ProductSize = apps.get_model("core", "ProductSize")

    for variant in ProductVariant.objects.all().iterator():
        attributes = variant.attributes or {}
        update_fields = []

        color_name = get_attr(attributes, ["Цвет", "цвет", "Color", "color"])
        if color_name and not variant.color_id:
            color, _ = ProductColor.objects.get_or_create(
                name=color_name,
                defaults={"hash_code": "#000000"},
            )
            variant.color = color
            update_fields.append("color")

        memory_volume = get_attr(attributes, ["Память", "память", "Memory", "memory"])
        if memory_volume and not variant.memory_id:
            memory, _ = Memory.objects.get_or_create(volume=memory_volume)
            variant.memory = memory
            update_fields.append("memory")

        size_name = get_attr(attributes, ["Размер", "размер", "Size", "size"])
        if size_name and not variant.size_id:
            size, _ = ProductSize.objects.get_or_create(name=size_name)
            variant.size = size
            update_fields.append("size")

        if update_fields:
            variant.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_alter_productimage_options"),
    ]

    operations = [
        migrations.RunPython(backfill_variant_options, migrations.RunPython.noop),
    ]
