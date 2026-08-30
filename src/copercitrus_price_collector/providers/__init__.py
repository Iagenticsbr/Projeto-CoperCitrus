"""Available product search providers."""

from .base import PriceProvider
from .bing_shopping import BingShoppingProvider
from .comparadores import BuscapeProvider, ZoomProvider
from .google_shopping import GoogleShoppingProvider
from .mercadolivre import MercadoLivreProvider
from .shopee import ShopeeProvider
from .shopee_affiliate import ShopeeWebProvider

__all__ = [
    "BingShoppingProvider",
    "BuscapeProvider",
    "GoogleShoppingProvider",
    "MercadoLivreProvider",
    "PriceProvider",
    "ShopeeProvider",
    "ShopeeWebProvider",
    "ZoomProvider",
]
