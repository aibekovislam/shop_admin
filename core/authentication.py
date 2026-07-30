from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

from .models import ShopAPIKey


class ShopAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Аутентификация для внешних клиентов API (Google Apps Script, будущие
    интеграции). Ожидает заголовок:

        Authorization: Bearer <ключ из ShopAPIKey>

    Ключ привязан к Shop напрямую, не к конкретному человеку — Apps Script
    в таблице действует "от имени магазина", а не от имени сотрудника.

    Возвращает (None, shop_api_key) — request.user остаётся анонимным,
    request.auth содержит ShopAPIKey с доступом к .shop.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization")
        if not header:
            return None

        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            raise exceptions.AuthenticationFailed(
                f"Invalid Authorization header. Expected: '{self.keyword} <key>'."
            )

        key = parts[1]

        try:
            api_key = ShopAPIKey.objects.select_related("shop").get(key=key, is_active=True)
        except ShopAPIKey.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or revoked API key.")

        if not api_key.shop.is_active:
            raise exceptions.AuthenticationFailed("Shop is inactive.")

        api_key.last_used_at = timezone.now()
        api_key.save(update_fields=["last_used_at"])

        return (None, api_key)


class HasShopAPIKey(permissions.BasePermission):
    """
    Разрешает доступ только если запрос прошёл аутентификацию через
    ShopAPIKeyAuthentication (request.auth содержит валидный ShopAPIKey).

    Обычный IsAuthenticated здесь не подходит: наша аутентификация не
    привязана к Django User (request.user остаётся анонимным), поэтому
    проверяем именно request.auth, а не request.user.
    """

    def has_permission(self, request, view):
        return isinstance(request.auth, ShopAPIKey)
