# Shop Admin

Мульти-магазинная админка для управления товарами/ценами/наличием.

## Запуск (Docker)

1. `cp .env.example .env`, поменять `SECRET_KEY`.
2. `docker compose up --build`
3. Во втором терминале:
   ```
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py createsuperuser
   ```
4. Открыть http://localhost:8000/admin/

## Модель данных (EPIC 1-2)

- `Shop` — магазин
- `Product` / `ProductVariant` — товар и его модификации (цвет/память и т.п. в JSON-поле `attributes`)
- `ProductImage` — фото, привязано к варианту (разные цвета — разные фото)
- `Channel` — канал сбыта (маркетплейс/розница/сайт) конкретного магазина
- `Stock` — наличие + оптовая цена, ОДНА запись на (variant, shop) — не дублируется по каналам
- `ChannelPrice` — цена продажи, разная по каждому каналу
- `ShopAPIKey` — ключ доступа к API для внешних клиентов (Google Sheets)

## REST API (EPIC 3)

Аутентификация: заголовок `Authorization: Bearer <ключ>`. Ключ создаётся в
админке (`Shop API keys`) для нужного магазина.

- `GET /api/shops/<shop_id>/variants/` — выгрузка каталога магазина
- `POST /api/shops/<shop_id>/variants/bulk_update/` — массовое обновление цен/наличия, построчный статус в ответе
- `POST /api/shops/<shop_id>/variants/create/` — создание нового товара

Пример `bulk_update`:
```json
{
  "changes": [
    {
      "variant_id": 1,
      "wholesale_price": "65000",
      "in_stock": true,
      "channel_prices": {"3": "79990", "4": "81990"}
    }
  ]
}
```

## Фото товаров

Загружаются в админке на странице варианта товара (Product variants → открыть
вариант → секция Images). Файлы хранятся на диске сервера (`MEDIA_ROOT`), в
базе — только путь.

**Важно для продакшена**: чтобы маркетплейсы могли забрать фото по URL,
сервер должен быть публично доступен по HTTPS (не localhost). При росте
нагрузки стоит вынести файлы в S3-совместимое хранилище — см. Backlog в
roadmap.md.

## M-Market

1. В админке создайте канал (`Channels`) для нужного магазина:
   - `name`: `MMarket Turan`
   - `channel_type`: `Маркетплейс`
   - `adapter_key`: `mmarket`
   - `api_url`: `https://m-market.kg/api/crm/products/import_products/`
   - `api_token`: токен M-Market
   - `branch_id`: ID филиала M-Market
2. В карточке SKU (`Product variants`) заполните описание товара, категорию,
   минимум 3 фото, характеристики, наличие и цену канала `MMarket Turan`.
3. Для отправки откройте `Channel prices`, выберите строки канала M-Market и
   выполните action `Отправить выбранные каналы в M-Market`.

Синхронизация отправляет все товары с ценой для выбранного канала одним
запросом. Автоматической отправки при каждом сохранении нет из-за лимита
M-Market: 1 запрос в 15 минут.
