from abc import ABC, abstractmethod


class MarketplaceAdapter(ABC):

    def __init__(self, channel):
        self.channel = channel
        self.shop = channel.shop


    @abstractmethod
    def build_payload(self, channel_price_ids=None):
        pass


    @abstractmethod
    def push_products(self, channel_price_ids=None):
        pass
