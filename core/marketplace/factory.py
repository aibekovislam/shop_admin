from .mmarket import MMarketAdapter
from .omarket import OMarketAdapter
from .bakai import BakaiMarketAdapter


def get_marketplace_adapter(channel):

    adapters = {
        "mmarket": MMarketAdapter,
        "omarket": OMarketAdapter,
        "omarketshat": OMarketAdapter,
        "bakai": BakaiMarketAdapter,
    }


    adapter = adapters.get(channel.adapter_key)


    if not adapter:
        raise Exception(
            f"Unknown adapter: {channel.adapter_key}"
        )


    return adapter(channel)
