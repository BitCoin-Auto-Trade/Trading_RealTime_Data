"""고속 인메모리 데이터 저장소"""

import time
from typing import Optional, List, Dict
from collections import deque
from sortedcontainers import SortedDict

from data_collector.data_normalizer import NormalizedTrade, NormalizedOrderBook
from utils.logger_utils import setup_logger


class HotStorage:
    """
    초저지연 인메모리 데이터 저장소

    특징:
    - Ring Buffer로 메모리 제한
    - 시간 기반 인덱싱 (빠른 조회)
    - TTL 기반 자동 삭제
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        max_trades: int = 10000,
        max_orderbooks: int = 1000,
        ttl_seconds: int = 3600  # 1시간
    ):
        self.symbol = symbol
        self.logger = setup_logger(f"hot_storage_{symbol}")

        # 최대 저장 개수
        self.max_trades = max_trades
        self.max_orderbooks = max_orderbooks
        self.ttl_seconds = ttl_seconds

        # 데이터 저장소 (Ring Buffer)
        self.trades: deque[NormalizedTrade] = deque(maxlen=max_trades)
        self.orderbooks: deque[NormalizedOrderBook] = deque(maxlen=max_orderbooks)

        # 시간 기반 인덱스 (빠른 범위 조회)
        self.trade_index: SortedDict = SortedDict()  # timestamp -> trade
        self.orderbook_index: SortedDict = SortedDict()  # timestamp -> orderbook

        # 최신 스냅샷 (O(1) 접근)
        self.latest_trade: Optional[NormalizedTrade] = None
        self.latest_orderbook: Optional[NormalizedOrderBook] = None

        # 통계
        self.total_trades_stored = 0
        self.total_orderbooks_stored = 0

    def add_trade(self, trade: NormalizedTrade):
        """체결 데이터 추가"""
        self.trades.append(trade)
        self.trade_index[trade.timestamp] = trade
        self.latest_trade = trade
        self.total_trades_stored += 1

        # TTL 체크 (오래된 데이터 삭제)
        self._cleanup_old_trades()

    def add_orderbook(self, orderbook: NormalizedOrderBook):
        """호가창 데이터 추가"""
        self.orderbooks.append(orderbook)
        self.orderbook_index[orderbook.timestamp] = orderbook
        self.latest_orderbook = orderbook
        self.total_orderbooks_stored += 1

        # TTL 체크
        self._cleanup_old_orderbooks()

    def get_latest_trade(self) -> Optional[NormalizedTrade]:
        """최신 체결 조회 (O(1))"""
        return self.latest_trade

    def get_latest_orderbook(self) -> Optional[NormalizedOrderBook]:
        """최신 호가창 조회 (O(1))"""
        return self.latest_orderbook

    def get_trades_since(self, timestamp_ms: int) -> List[NormalizedTrade]:
        """특정 시간 이후 체결 조회 (O(log N + K))"""
        return [
            trade for ts, trade in self.trade_index.items()
            if ts >= timestamp_ms
        ]

    def get_trades_range(
        self,
        start_ms: int,
        end_ms: int
    ) -> List[NormalizedTrade]:
        """시간 범위 체결 조회 (O(log N + K))"""
        return [
            trade for ts, trade in self.trade_index.items()
            if start_ms <= ts <= end_ms
        ]

    def get_recent_trades(self, count: int = 100) -> List[NormalizedTrade]:
        """최근 N개 체결 조회 (O(N))"""
        return list(self.trades)[-count:] if len(self.trades) >= count else list(self.trades)

    def get_orderbooks_since(self, timestamp_ms: int) -> List[NormalizedOrderBook]:
        """특정 시간 이후 호가창 조회"""
        return [
            ob for ts, ob in self.orderbook_index.items()
            if ts >= timestamp_ms
        ]

    def get_recent_orderbooks(self, count: int = 10) -> List[NormalizedOrderBook]:
        """최근 N개 호가창 조회"""
        return list(self.orderbooks)[-count:] if len(self.orderbooks) >= count else list(self.orderbooks)

    def get_trades_in_window(self, window_seconds: int) -> List[NormalizedTrade]:
        """최근 N초 체결 조회"""
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - (window_seconds * 1000)
        return self.get_trades_since(start_ms)

    def calculate_volume_in_window(self, window_seconds: int) -> float:
        """최근 N초 거래량 계산"""
        trades = self.get_trades_in_window(window_seconds)
        return sum(t.quantity for t in trades)

    def calculate_vwap_in_window(self, window_seconds: int) -> Optional[float]:
        """최근 N초 VWAP 계산"""
        trades = self.get_trades_in_window(window_seconds)
        if not trades:
            return None

        total_pq = sum(t.price * t.quantity for t in trades)
        total_qty = sum(t.quantity for t in trades)

        if total_qty == 0:
            return None

        return total_pq / total_qty

    def get_large_trades_in_window(
        self,
        window_seconds: int
    ) -> List[NormalizedTrade]:
        """최근 N초 대형 거래 조회"""
        trades = self.get_trades_in_window(window_seconds)
        return [t for t in trades if t.is_large_trade]

    def get_stats(self) -> dict:
        """저장소 통계"""
        return {
            "symbol": self.symbol,
            "trades_in_memory": len(self.trades),
            "orderbooks_in_memory": len(self.orderbooks),
            "total_trades_stored": self.total_trades_stored,
            "total_orderbooks_stored": self.total_orderbooks_stored,
            "trade_index_size": len(self.trade_index),
            "orderbook_index_size": len(self.orderbook_index),
            "latest_trade_timestamp": (
                self.latest_trade.timestamp if self.latest_trade else None
            ),
            "latest_orderbook_timestamp": (
                self.latest_orderbook.timestamp if self.latest_orderbook else None
            )
        }

    def _cleanup_old_trades(self):
        """TTL 기반 오래된 체결 삭제"""
        if not self.trade_index:
            return

        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - (self.ttl_seconds * 1000)

        # TTL 지난 데이터 삭제
        keys_to_delete = [
            ts for ts in self.trade_index.keys()
            if ts < cutoff_ms
        ]

        for ts in keys_to_delete:
            del self.trade_index[ts]

        if keys_to_delete:
            self.logger.debug(
                f"Cleaned up {len(keys_to_delete)} old trades "
                f"(older than {self.ttl_seconds}s)"
            )

    def _cleanup_old_orderbooks(self):
        """TTL 기반 오래된 호가창 삭제"""
        if not self.orderbook_index:
            return

        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - (self.ttl_seconds * 1000)

        keys_to_delete = [
            ts for ts in self.orderbook_index.keys()
            if ts < cutoff_ms
        ]

        for ts in keys_to_delete:
            del self.orderbook_index[ts]

        if keys_to_delete:
            self.logger.debug(
                f"Cleaned up {len(keys_to_delete)} old orderbooks "
                f"(older than {self.ttl_seconds}s)"
            )

    def clear(self):
        """전체 데이터 삭제"""
        self.trades.clear()
        self.orderbooks.clear()
        self.trade_index.clear()
        self.orderbook_index.clear()
        self.latest_trade = None
        self.latest_orderbook = None
        self.logger.info(f"Storage cleared for {self.symbol}")

    def __repr__(self):
        return (
            f"HotStorage(symbol={self.symbol}, "
            f"trades={len(self.trades)}, "
            f"orderbooks={len(self.orderbooks)})"
        )
