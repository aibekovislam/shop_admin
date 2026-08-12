# Generated manually for Django 5.2

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_alter_brand_options_alter_brandcategory_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Memory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("volume", models.CharField(max_length=50, unique=True, verbose_name="Объём памяти")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
            ],
            options={
                "verbose_name": "Память",
                "verbose_name_plural": "Память",
                "ordering": ["volume"],
            },
        ),
        migrations.CreateModel(
            name="ProductColor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Название")),
                ("hash_code", models.CharField(default="#000000", max_length=25, verbose_name="HEX-код цвета")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
            ],
            options={
                "verbose_name": "Цвет товара",
                "verbose_name_plural": "Цвета товаров",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ProductSize",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Размер")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
            ],
            options={
                "verbose_name": "Размер",
                "verbose_name_plural": "Размеры",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="productimage",
            name="color",
            field=models.ForeignKey(
                blank=True,
                help_text="Если фото относится к конкретному цвету, выберите цвет.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="images",
                to="core.productcolor",
                verbose_name="Цвет",
            ),
        ),
        migrations.AddField(
            model_name="productvariant",
            name="color",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="variants",
                to="core.productcolor",
                verbose_name="Цвет",
            ),
        ),
        migrations.AddField(
            model_name="productvariant",
            name="memory",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="variants",
                to="core.memory",
                verbose_name="Память",
            ),
        ),
        migrations.AddField(
            model_name="productvariant",
            name="size",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="variants",
                to="core.productsize",
                verbose_name="Размер",
            ),
        ),
    ]
