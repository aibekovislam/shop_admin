from celery import shared_task

from core.models import Channel
from core.marketplace.factory import get_marketplace_adapter



@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def sync_marketplace_products(self, channel_id):

    try:

        channel = Channel.objects.get(
            id=channel_id
        )

        adapter = get_marketplace_adapter(channel)

        result = adapter.push_products()


        return {
            "channel": channel.name,
            "result": result
        }


    except Exception as exc:

        raise self.retry(
            exc=exc
        )
