from .mmarket import MMarketAdapter
from .omarket import OMarketAdapter
from .bakaimarket import BakaiMarketAdapter


def get_adapter(channel):

    if channel.slug == "mmarket":
        return MMarketAdapter(channel)

    if channel.slug == "omarket":
        return OMarketAdapter(channel)

    if channel.slug == "bakaimarket":
        return BakaiMarketAdapter(channel)