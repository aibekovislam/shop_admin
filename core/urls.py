from django.urls import path

from . import views

urlpatterns = [
    path("shops/<int:shop_id>/variants/", views.VariantListView.as_view(), name="variant-list"),
    path(
        "shops/<int:shop_id>/variants/bulk_update/",
        views.BulkUpdateView.as_view(),
        name="variant-bulk-update",
    ),
    path(
        "shops/<int:shop_id>/variants/create/",
        views.CreateVariantView.as_view(),
        name="variant-create",
    ),
]
