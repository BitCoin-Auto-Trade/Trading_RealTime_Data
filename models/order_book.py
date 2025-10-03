from dataclasses import dataclass
from typing import List


@dataclass
class OrderBook:
    event_type: str  # "depthUpdate"
    event_time: int  # E
    symbol: str      # s
    first_update_id: int  # U
    final_update_id: int  # u
    bids: List[List[str]]  # b: [["price", "quantity"], ...]
    asks: List[List[str]]  # a: [["price", "quantity"], ...]