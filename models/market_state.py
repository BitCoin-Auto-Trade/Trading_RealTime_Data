from dataclasses import dataclass
from typing import Optional

@dataclass
class MarketState:
    current_price: float
    current_volume: float
    bid_volume: float
    ask_volume: float
    imbalance: float
    volume_spike: bool
    timestamp: int


@dataclass
class Position:
    side: str
    entry_price: float
    quantity: float
    leverage: int
    timestamp: int
    unrealized_pnl: Optional[float] = None