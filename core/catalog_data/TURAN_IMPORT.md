# WEBSITE TURAN

`load_turan_catalog` reads the inventory section and applies the prices from
`Price Turan .xlsx`, using 88 KGS/USD and a 15% wholesale markup. The curated
web-price fallback uses a 10% markup. Used, damaged and zero-stock rows are excluded.

The command targets only shop 3, channels 8 (`omarket`) and 11 (`turan_bakai`).
It does not change existing SHAT products, prices, stock or channel settings.

## Data requirements

The command reuses exact-name source cards from the database. It does not search
the internet or invent missing product specifications. An optional `--catalog`
JSON object can supply explicit source SKU mappings or full new cards keyed by
the original Excel product name:

```json
{
  "EXACT EXCEL PRODUCT NAME": {
    "source_sku": "EXISTING-SKU"
  }
}
```

A full card requires `name`, `brand`, `category`, `description`, `attributes`
(including confirmed new condition), and three distinct HTTPS JPG/PNG `images`.
`category_id` and `market_specs` can explicitly resolve the category and enum
values using the supplied schema. Arbitrary attribute IDs are not inherited.
Price and stock always come from the inventory audit, not from this JSON.

Without `--send`, the command only reads data and writes a report. With `--send`,
it requires the entire inventory to resolve before downloading images or making
any database changes. Missing source cards are listed in the report together
with available source metadata. There is no silent partial-catalog import.

Existing TURAN listings under another SKU block duplicate creation and need an
explicit reconciliation before importing that row. Imported cards use dedicated
stable TURAN SKUs. Image bytes are stored without image transformations, under
content-addressed filenames. Three duplicate image files are rejected even when
their URLs differ. Visual inspection is not part of the command.

## Execution

```bash
python manage.py load_turan_catalog \
  --stock '/app/Остатки Товаров Бишкек .xlsx' \
  --prices '/app/Price Turan .xlsx' \
  --schema /app/turan_market_schema.json \
  --report /app/turan_import_report.json \
  --send
```

All database cards and adapter payloads are validated before the transaction
commits. Marketplace requests happen after commit: O!Market batches are at most
100 items and Bakai batches at most 1000. Requests are not automatically retried
by this command. The existing hourly synchronization remains enabled and can
pick up committed records; a transport failure may therefore require checking
both the marketplace and scheduler before a manual retry. An accepted request
does not prove that all products have passed import processing or moderation.

No production execution has been verified from the local development environment.
