import requests

from .base import MarketplaceAdapter

from core.models import (
    ProductVariant,
    Stock,
    ChannelPrice,
)


class MMarketAdapter(MarketplaceAdapter):

    def __init__(self, channel):
        self.channel = channel
        self.shop = channel.shop

    def build_payload(self):

        products = []

        variants = ProductVariant.objects.filter(
            is_active=True,
            stocks__shop=self.shop,
        ).select_related(
            "product",
        ).prefetch_related(
            "images",
            "stocks",
            "channel_prices",
        )

        for variant in variants:
            stock = variant.stocks.filter(
                shop=self.shop
            ).first()

            price = variant.channel_prices.filter(
                shop=self.shop,
                channel=self.channel
            ).first()

            if not price or price.price < 0.01:
                continue

            images = [
                f"https://shop.kkode.site{image.image.url}"
                for image in variant.images.all()
            ]

            product = {
                "sku": variant.sku,
                "name": variant.product.name,
                "category": variant.product.category,
                "price": str(price.price) if price else "0",
                "description": variant.product.description,
                "images": images,
                "specs": {
                    key: value
                    for key, value in variant.attributes.items()
                    if value
                },
                "stock": [
                    {
                        "quantity": 1 if stock and stock.in_stock else 0,
                        "branch_id": self.channel.branch_id,
                    }
                ],
            }

            products.append(product)

        return {
            "products": products
        }

    def push_products(self):
        payload = self.build_payload()
        print("MMARKET URL:", self.channel.api_url)
        print("MMARKET HEADERS:", {"Authorization": f"Token {self.channel.api_token}"})
        print("MMARKET PAYLOAD:", payload)

        response = requests.post(
            self.channel.api_url,
            json=payload,
            headers={
                "Authorization": f"Token {self.channel.api_token}"
            },
            timeout=30,
        )

        if response.status_code != 200:
            raise Exception(
                f"MMarket error {response.status_code}: {response.text}"
            )

        return response.json()

    def pull_orders(self):
        pass
