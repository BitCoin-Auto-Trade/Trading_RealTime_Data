"""데이터 정규화 및 보강 모듈"""

from typing import List, Optional
from dataclasses import dataclass
from collections import deque

from models.order_book import OrderBook
from models.trade import Trade
from utils.logger_utils import setup_logger


@dataclass
class NormalizedTrade:
    """정규화된 체결 데이터"""
    # 원본 데이터
    timestamp: int
    symbol: str
    trade_id: int
    price: float
    quantity: float
    is_buyer_maker: bool

    # 계산된 필드
    amount_usdt: float          # 거래 대금
    side: str                   # "BUY" | "SELL"

    # 추가 메타데이터
    is_large_trade: bool = False
    vwap: Optional[float] = None
    cumulative_volume: Optional[float] = None


@dataclass
class NormalizedOrderBook:
    """정규화된 호가창 데이터"""
    # 원본 데이터
    timestamp: int
    symbol: str
    update_id: int

    # 가격 정보
    best_bid: float
    best_ask: float
    mid_price: float            # (best_bid + best_ask) / 2
    spread: float               # best_ask - best_bid
    spread_bps: float           # spread / mid_price * 10000 (basis points)

    # 물량 정보
    total_bid_volume: float     # 매수 호가 총 물량 (상위 N개)
    total_ask_volume: float     # 매도 호가 총 물량 (상위 N개)
    bid_ask_ratio: float        # total_bid_volume / total_ask_volume
    imbalance: float            # (bid - ask) / (bid + ask), -1 ~ 1

    # 원본 호가 (상위 5개)
    bids: List[tuple[float, float]]  # [(price, quantity), ...]
    asks: List[tuple[float, float]]


class DataNormalizer:
    """실시간 데이터 정규화 및 보강"""

    def __init__(self, large_trade_threshold: float = 10000.0, orderbook_depth: int = 5):
        """
        Args:
            large_trade_threshold: 대형 거래 임계값 (USDT)
            orderbook_depth: 호가창 집계 깊이
        """
        self.logger = setup_logger("data_normalizer")
        self.large_trade_threshold = large_trade_threshold
        self.orderbook_depth = orderbook_depth

        # VWAP 계산용 (최근 100개 거래)
        self.recent_trades: deque = deque(maxlen=100)
        self.cumulative_volume: float = 0.0

    def normalize_trade(self, trade: Trade) -> NormalizedTrade:
        """체결 데이터 정규화"""
        price = float(trade.price)
        quantity = float(trade.quantity)
        amount_usdt = price * quantity

        # 거래 방향
        side = "SELL" if trade.is_buyer_maker else "BUY"

        # 대형 거래 감지
        is_large_trade = amount_usdt >= self.large_trade_threshold

        # VWAP 계산 (최근 거래 기준)
        vwap = self._calculate_vwap()

        # 누적 거래량
        self.cumulative_volume += quantity

        # 최근 거래에 추가
        self.recent_trades.append((price, quantity, amount_usdt))

        normalized = NormalizedTrade(
            timestamp=trade.trade_time,
            symbol=trade.symbol,
            trade_id=trade.aggregate_trade_id,
            price=price,
            quantity=quantity,
            is_buyer_maker=trade.is_buyer_maker,
            amount_usdt=amount_usdt,
            side=side,
            is_large_trade=is_large_trade,
            vwap=vwap,
            cumulative_volume=self.cumulative_volume
        )

        if is_large_trade:
            self.logger.info(
                f"[대형거래] {side} {amount_usdt:,.0f} USDT | "
                f"가격: {price:,.2f} | 수량: {quantity:.4f}"
            )

        return normalized

    def normalize_orderbook(self, orderbook: OrderBook) -> NormalizedOrderBook:
        """호가창 데이터 정규화"""
        # 호가 파싱
        bids = [(float(b[0]), float(b[1])) for b in orderbook.bids[:self.orderbook_depth]]
        asks = [(float(a[0]), float(a[1])) for a in orderbook.asks[:self.orderbook_depth]]

        if not bids or not asks:
            self.logger.warning("Empty bids or asks in orderbook")
            # 기본값 반환
            return self._create_empty_normalized_orderbook(orderbook)

        # 최우선 호가
        best_bid = bids[0][0]
        best_ask = asks[0][0]

        # 중간 가격 및 스프레드
        mid_price = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        spread_bps = (spread / mid_price) * 10000 if mid_price > 0 else 0

        # 총 물량 계산 (상위 N개)
        total_bid_volume = sum(qty for _, qty in bids)
        total_ask_volume = sum(qty for _, qty in asks)

        # 비율 및 불균형
        bid_ask_ratio = (
            total_bid_volume / total_ask_volume
            if total_ask_volume > 0
            else 0
        )

        total = total_bid_volume + total_ask_volume
        imbalance = (
            (total_bid_volume - total_ask_volume) / total
            if total > 0
            else 0
        )

        normalized = NormalizedOrderBook(
            timestamp=orderbook.event_time,
            symbol=orderbook.symbol,
            update_id=orderbook.final_update_id,
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid_price,
            spread=spread,
            spread_bps=spread_bps,
            total_bid_volume=total_bid_volume,
            total_ask_volume=total_ask_volume,
            bid_ask_ratio=bid_ask_ratio,
            imbalance=imbalance,
            bids=bids,
            asks=asks
        )

        self.logger.debug(
            f"[호가창] 중간가: {mid_price:,.2f} | 스프레드: {spread:.2f} ({spread_bps:.1f}bps) | "
            f"불균형: {imbalance:+.3f} | 비율: {bid_ask_ratio:.3f}"
        )

        return normalized

    def _calculate_vwap(self) -> Optional[float]:
        """VWAP 계산 (Volume Weighted Average Price)"""
        if not self.recent_trades:
            return None

        total_pq = sum(price * qty for price, qty, _ in self.recent_trades)
        total_qty = sum(qty for _, qty, _ in self.recent_trades)

        if total_qty == 0:
            return None

        return total_pq / total_qty

    def _create_empty_normalized_orderbook(
        self,
        orderbook: OrderBook
    ) -> NormalizedOrderBook:
        """빈 호가창 생성 (에러 시 기본값)"""
        return NormalizedOrderBook(
            timestamp=orderbook.event_time,
            symbol=orderbook.symbol,
            update_id=orderbook.final_update_id,
            best_bid=0.0,
            best_ask=0.0,
            mid_price=0.0,
            spread=0.0,
            spread_bps=0.0,
            total_bid_volume=0.0,
            total_ask_volume=0.0,
            bid_ask_ratio=0.0,
            imbalance=0.0,
            bids=[],
            asks=[]
        )

    def reset(self):
        """상태 초기화"""
        self.recent_trades.clear()
        self.cumulative_volume = 0.0
        self.logger.info("DataNormalizer reset")
