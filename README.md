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
- `Stock` — количество + наличие + оптовая цена, ОДНА запись на (variant, shop) — не дублируется по каналам
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
      "quantity": 7,
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
   минимум 3 фото, характеристики, наличие, количество и цену канала `MMarket Turan`.
3. Для отправки откройте `Channel prices`, выберите строки канала M-Market и
   выполните action `Отправить выбранные каналы в M-Market`.

Для M-Market в `attributes` обязательны точные ключи:

```json
{
  "Тип": "Смартфон",
  "Производители": "Apple",
  "Модель": "iPhone 15 128GB",
  "Цвет": "Чёрный"
}
```

Ключи чувствительны к написанию: `Цвет` и `цвет` — разные характеристики.
Поля O!Market с префиксом `omarket_` в M-Market не отправляются.

Синхронизация отправляет все товары с ценой для выбранного канала одним
запросом. Автоматической отправки при каждом сохранении нет из-за лимита
M-Market: 1 запрос в 15 минут.

## O!Market

1. В админке создайте канал (`Channels`) для нужного магазина:
   - `name`: `O!Market`
   - `channel_type`: `Маркетплейс`
   - `adapter_key`: `omarket`
   - `api_url`: `https://stage-api-market.o.kg/` для теста или `https://api-market.o.kg/` для прода
   - `api_token`: токен O!Market
2. В карточке SKU (`Product variants`) заполните фото, описание, наличие, количество и
   цену канала `O!Market`.
3. В `attributes` SKU добавьте обязательные поля O!Market:

```json
{
  "цвет": "чёрный",
  "память": "128GB",
  "omarket_category_id": 1,
  "omarket_width": 10,
  "omarket_height": 5,
  "omarket_length": 15,
  "omarket_weight": 0.5,
  "omarket_attributes": [
    {
      "attribute_id": 1208,
      "value_id": 8132
    }
  ]
}
```

В админке `attributes` заполняются не сырым JSON, а строками `Ключ` /
`Значение`. Например: `цвет = чёрный`, `память = 128GB`,
`omarket_category_id = 1`.

`omarket_attributes` необязателен, но `omarket_category_id` и габариты нужны
для импорта. Action `Отправить выбранные каналы в маркетплейс` использует
endpoint `/api/mia/v1/product/import/create-or-update/`, поэтому отсутствующие
в выгрузке товары не деактивируются.

## Bakai Market

1. В админке создайте канал (`Channels`) для нужного магазина:
   - `name`: `Bakai Market`
   - `channel_type`: `Маркетплейс`
   - `adapter_key`: `bakai`
   - `api_url`: `https://api.bakai.store/product-service-go/v1/merchant-api/create`
   - `api_token`: токен Bakai Market
   - `branch_id`: ID филиала Bakai Market
2. В карточке SKU (`Product variants`) заполните описание товара, категорию,
   минимум 3 фото, наличие, количество и цену канала `Bakai Market`.
3. В `attributes` SKU укажите бренд одним из ключей:

```json
{
  "Бренд": "Apple",
  "Цвет": "Чёрный",
  "Память": "128GB"
}
```

Также поддерживаются ключи `brand`, `Производитель`, `Производители`. Бренд
уйдёт в обязательное поле `brand_name`, остальные обычные характеристики
уйдут в `attributes` формата `{"name": "...", "value": "..."}`. Поля с
префиксами `omarket_` и `bakai_` в характеристики Bakai Market не отправляются.

## Остатки

Количество товара меняется в `Stock`:

- `quantity` — фактическое количество, которое уйдёт в маркетплейсы.
- `in_stock` — общий переключатель наличия. Если выключен, в маркетплейсы
  уйдёт `quantity = 0`, даже если в поле `quantity` стоит число.
