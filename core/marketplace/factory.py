from .mmarket import MMarketAdapter


def get_marketplace_adapter(channel):

    adapters = {
        "mmarket": MMarketAdapter,
    }


    adapter = adapters.get(channel.adapter_key)


    if not adapter:
        raise Exception(
            f"Unknown adapter: {channel.adapter_key}"
        )


    return adapter(channel)
