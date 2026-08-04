from abc import ABC, abstractmethod


class MarketplaceAdapter(ABC):

    @abstractmethod
    def push_products(self):
        pass


    @abstractmethod
    def pull_orders(self):
        pass