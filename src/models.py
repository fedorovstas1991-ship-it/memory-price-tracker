from dataclasses import dataclass
from datetime import datetime


@dataclass
class PriceEntry:
    chip_type: str
    part_number: str
    description: str
    capacity: str
    source: str
    price_usd: float
    price_rub: float
    moq: int
    url: str
    fetched_at: datetime

    def to_sheets_row(self) -> list:
        return [
            self.chip_type,
            self.part_number,
            self.description,
            self.capacity,
            self.source,
            self.price_usd,
            self.price_rub,
            self.moq,
            self.url,
            self.fetched_at.strftime("%Y-%m-%d %H:%M UTC"),
        ]

    def to_history_row(self) -> list:
        return [
            self.fetched_at.strftime("%Y-%m-%d"),
            self.chip_type,
            self.part_number,
            self.source,
            self.price_usd,
        ]
