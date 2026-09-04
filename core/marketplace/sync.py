import logging
from decimal import Decimal

from django.conf import settings
from django.db.models import Q

from core.marketplace.factory import get_marketplace_adapter
from core.models import Channel, ChannelPrice


logger = logging.getLogger(__name__)

SHAT_MARKET_ADAPTER_KEYS = ("mmarket", "omarketshat", "bakai")
SHAT_MMARKET_BRANCH_IDS = (677,)
DEFAULT_BATCH_SIZES = {
    "mmarket": 5000,
    "omarketshat": 100,
    "bakai": 1000,
}


def sync_shat_marketplaces(channel_ids=None, dry_run=False):
    channels = list_shat_market_channels(channel_ids)
    result = {
        "dry_run": dry_run,
        "channels": [],
        "total_sent": 0,
        "total_skipped": 0,
        "errors": [],
    }

    for channel in channels:
        channel_result = sync_channel(channel, dry_run=dry_run)
        result["channels"].append(channel_result)
        result["total_sent"] += channel_result["sent"]
        result["total_skipped"] += channel_result["skipped"]
        result["errors"].extend(channel_result["errors"])

    return result


def list_shat_market_channels(channel_ids=None):
    configured_ids = parse_ids(channel_ids if channel_ids is not None else getattr(settings, "SHAT_MARKET_CHANNEL_IDS", []))
    if configured_ids:
        return Channel.objects.filter(id__in=configured_ids, is_active=True).order_by("id")

    return (
        Channel.objects.filter(
            adapter_key__in=SHAT_MARKET_ADAPTER_KEYS,
            is_active=True,
        )
        .filter(
            Q(adapter_key__in=("omarketshat", "bakai"))
            | Q(name__icontains="SHAT")
            | Q(shop__name__icontains="SHAT")
            | Q(adapter_key="mmarket", branch_id__in=SHAT_MMARKET_BRANCH_IDS)
        )
        .order_by("id")
    )


def sync_channel(channel, dry_run=False):
    price_ids, skipped = eligible_channel_price_ids(channel)
    channel_result = {
        "channel_id": channel.id,
        "channel": channel.name,
        "adapter_key": channel.adapter_key,
        "eligible": len(price_ids),
        "sent": 0,
        "skipped": len(skipped),
        "skipped_items": skipped[:50],
        "batches": [],
        "errors": [],
    }
    if not price_ids:
        return channel_result

    adapter = get_marketplace_adapter(channel)
    batch_size = DEFAULT_BATCH_SIZES.get(channel.adapter_key, 100)
    for index, batch_ids in enumerate(chunks(price_ids, batch_size), start=1):
        batch_result = {
            "batch": index,
            "channel_price_ids": len(batch_ids),
            "sent": 0,
            "response": None,
            "error": "",
        }
        try:
            payload = adapter.build_payload(channel_price_ids=batch_ids)
            batch_result["sent"] = len(payload.get("products", []))
            if dry_run:
                batch_result["response"] = {"dry_run": True}
            else:
                batch_result["response"] = adapter.push_products(channel_price_ids=batch_ids)
            channel_result["sent"] += batch_result["sent"]
        except Exception as exc:
            message = f"{channel.name} batch {index}: {exc}"
            logger.exception("SHAT marketplace sync failed: %s", message)
            batch_result["error"] = str(exc)
            channel_result["errors"].append(message)
            if not dry_run:
                ChannelPrice.objects.filter(id__in=batch_ids).update(
                    sync_status=ChannelPrice.SyncStatus.ERROR,
                    last_sync_error=str(exc),
                )
        channel_result["batches"].append(batch_result)

    return channel_result


def eligible_channel_price_ids(channel):
    prices = (
        ChannelPrice.objects.filter(
            shop=channel.shop,
            channel=channel,
            variant__is_active=True,
            price__gte=Decimal("0.01"),
        )
        .select_related("variant__product")
        .order_by("variant__sku", "id")
    )
    ids = []
    skipped = []
    for price in prices:
        reason = skip_reason(price)
        if reason:
            skipped.append({"sku": price.variant.sku, "reason": reason})
            continue
        ids.append(price.id)
    return ids, skipped


def skip_reason(price):
    variant = price.variant
    attrs = variant.attributes if isinstance(variant.attributes, dict) else {}
    text = " ".join(
        str(value)
        for value in (
            variant.sku,
            variant.product.name,
            attrs.get("Состояние", ""),
        )
    ).upper()
    if "B/U" in text or "Б/У" in text or "Б.У" in text or "DAMAGED" in text:
        return "Б/У или damaged не грузим на маркет"
    return ""


def parse_ids(value):
    if not value:
        return []
    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = value
    ids = []
    for item in raw_items:
        item = str(item).strip()
        if item:
            ids.append(int(item))
    return ids


def chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index : index + size]
