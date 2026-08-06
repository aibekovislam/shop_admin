from abc import ABC, abstractmethod


class MarketplaceAdapter(ABC):

    def __init__(self, channel):
        self.channel = channel
        self.shop = channel.shop


    @abstractmethod
    def build_payload(self):
        pass


    @abstractmethod
    def push_products(self):
        pass
