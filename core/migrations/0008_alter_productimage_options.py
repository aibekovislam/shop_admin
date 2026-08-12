# Generated manually for Django 5.2

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_memory_productcolor_productsize_and_variant_options"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="productimage",
            options={
                "ordering": ["created_at", "id"],
                "verbose_name": "Фото товара",
                "verbose_name_plural": "Фото товаров",
            },
        ),
    ]
