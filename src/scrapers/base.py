from abc import ABC, abstractmethod
from src.models import PriceEntry


class BaseScraper(ABC):
    name: str

    @abstractmethod
    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        """Fetch prices for all watchlist items. Returns list of PriceEntry."""
        ...
