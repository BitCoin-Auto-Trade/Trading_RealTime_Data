"""시장 상태 실시간 관리"""

import time
from typing import Optional
from dataclasses import dataclass, field
from collections import deque

from data_collector.data_normalizer import NormalizedTrade, NormalizedOrderBook
from utils.logger_utils import setup_logger


@dataclass
class MarketState:
    """시장 상태 스냅샷"""
    timestamp: int
    symbol: str

    # 가격 정보
    last_price: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0
    mid_price: float = 0.0

    # 호가창 정보
    total_bid_volume: float = 0.0
    total_ask_volume: float = 0.0
    bid_ask_ratio: float = 0.0
    bid_ask_imbalance: float = 0.0  # -1 (매도 압도) ~ +1 (매수 압도)

    # 거래량 정보
    recent_volume_1m: float = 0.0   # 최근 1분 거래량
    recent_volume_5m: float = 0.0   # 최근 5분 거래량
    vwap_1m: float = 0.0            # 1분 VWAP

    # 시그널 관련
    price_momentum: float = 0.0     # 가격 변화율 (5초)
    volume_spike: bool = False      # 거래량 급증 감지
    large_trade_count: int = 0      # 최근 1분 대형 거래 횟수

    # 메타데이터
    trade_count: int = 0
    orderbook_count: int = 0
    last_trade_timestamp: int = 0
    last_orderbook_timestamp: int = 0


class MarketStateManager:
    """시장 상태 실시간 업데이트 및 특징 계산"""

    def __init__(self, symbol: str = "BTCUSDT"):
        self.symbol = symbol
        self.logger = setup_logger(f"market_state_{symbol}")

        # 현재 상태
        self.state = MarketState(
            timestamp=int(time.time() * 1000),
            symbol=symbol
        )

        # 거래 히스토리 (최근 5분)
        self.trade_history: deque = deque(maxlen=5000)  # 최대 5000개
        self.large_trade_history: deque = deque(maxlen=100)

        # 가격 히스토리 (가격 모멘텀 계산용)
        self.price_history: deque = deque(maxlen=100)

    def update_from_trade(self, trade: NormalizedTrade):
        """체결 데이터로 상태 업데이트"""
        self.state.trade_count += 1
        self.state.last_price = trade.price
        self.state.last_trade_timestamp = trade.timestamp

        # 거래 히스토리에 추가
        self.trade_history.append({
            'timestamp': trade.timestamp,
            'price': trade.price,
            'quantity': trade.quantity,
            'amount_usdt': trade.amount_usdt,
            'is_large': trade.is_large_trade
        })

        # 가격 히스토리 추가
        self.price_history.append({
            'timestamp': trade.timestamp,
            'price': trade.price
        })

        # 대형 거래 추적
        if trade.is_large_trade:
            self.large_trade_history.append({
                'timestamp': trade.timestamp,
                'amount_usdt': trade.amount_usdt,
                'side': trade.side
            })

        # 거래량 및 특징 재계산
        self._update_volume_metrics()
        self._update_price_momentum()
        self._update_large_trade_count()

        self.state.timestamp = int(time.time() * 1000)

    def update_from_orderbook(self, orderbook: NormalizedOrderBook):
        """호가창 데이터로 상태 업데이트"""
        self.state.orderbook_count += 1
        self.state.last_orderbook_timestamp = orderbook.timestamp

        # 호가 정보 업데이트
        self.state.best_bid = orderbook.best_bid
        self.state.best_ask = orderbook.best_ask
        self.state.mid_price = orderbook.mid_price
        self.state.spread = orderbook.spread
        self.state.spread_bps = orderbook.spread_bps

        # 호가창 물량 정보
        self.state.total_bid_volume = orderbook.total_bid_volume
        self.state.total_ask_volume = orderbook.total_ask_volume
        self.state.bid_ask_ratio = orderbook.bid_ask_ratio
        self.state.bid_ask_imbalance = orderbook.imbalance

        self.state.timestamp = int(time.time() * 1000)

    def get_current_state(self) -> MarketState:
        """현재 시장 상태 반환"""
        return self.state

    def get_features(self) -> dict:
        """시그널 생성용 특징 반환"""
        return {
            # 가격 정보
            'last_price': self.state.last_price,
            'mid_price': self.state.mid_price,
            'spread_bps': self.state.spread_bps,

            # 호가 정보
            'imbalance': self.state.bid_ask_imbalance,
            'bid_ask_ratio': self.state.bid_ask_ratio,

            # 거래량 정보
            'volume_1m': self.state.recent_volume_1m,
            'volume_5m': self.state.recent_volume_5m,
            'vwap_1m': self.state.vwap_1m,

            # 시그널
            'price_momentum': self.state.price_momentum,
            'volume_spike': self.state.volume_spike,
            'large_trade_count': self.state.large_trade_count,

            # 메타
            'trade_count': self.state.trade_count,
            'orderbook_count': self.state.orderbook_count
        }

    def _update_volume_metrics(self):
        """거래량 메트릭 업데이트"""
        now = time.time() * 1000  # milliseconds

        # 최근 1분 거래량
        volume_1m = sum(
            t['quantity'] for t in self.trade_history
            if now - t['timestamp'] <= 60_000
        )

        # 최근 5분 거래량
        volume_5m = sum(
            t['quantity'] for t in self.trade_history
            if now - t['timestamp'] <= 300_000
        )

        # 1분 VWAP
        recent_1m = [
            t for t in self.trade_history
            if now - t['timestamp'] <= 60_000
        ]
        if recent_1m:
            total_pq = sum(t['price'] * t['quantity'] for t in recent_1m)
            total_qty = sum(t['quantity'] for t in recent_1m)
            vwap_1m = total_pq / total_qty if total_qty > 0 else 0.0
        else:
            vwap_1m = 0.0

        self.state.recent_volume_1m = volume_1m
        self.state.recent_volume_5m = volume_5m
        self.state.vwap_1m = vwap_1m

        # 거래량 급증 감지 (1분 > 5분 평균의 2배)
        avg_volume_per_min = volume_5m / 5 if volume_5m > 0 else 0
        self.state.volume_spike = volume_1m > avg_volume_per_min * 2

    def _update_price_momentum(self):
        """가격 모멘텀 계산 (최근 5초 변화율)"""
        if len(self.price_history) < 2:
            self.state.price_momentum = 0.0
            return

        now = time.time() * 1000
        window_ms = 5000  # 5초

        # 최근 5초 가격
        recent_prices = [
            p for p in self.price_history
            if now - p['timestamp'] <= window_ms
        ]

        if len(recent_prices) < 2:
            self.state.price_momentum = 0.0
            return

        start_price = recent_prices[0]['price']
        end_price = recent_prices[-1]['price']

        momentum = (end_price - start_price) / start_price if start_price > 0 else 0.0
        self.state.price_momentum = momentum

    def _update_large_trade_count(self):
        """최근 1분 대형 거래 횟수"""
        now = time.time() * 1000
        window_ms = 60_000  # 1분

        count = sum(
            1 for t in self.large_trade_history
            if now - t['timestamp'] <= window_ms
        )

        self.state.large_trade_count = count

    def reset(self):
        """상태 초기화"""
        self.state = MarketState(
            timestamp=int(time.time() * 1000),
            symbol=self.symbol
        )
        self.trade_history.clear()
        self.large_trade_history.clear()
        self.price_history.clear()
        self.logger.info(f"Market state reset for {self.symbol}")

    def log_state(self):
        """현재 상태 로깅"""
        self.logger.info(
            f"[{self.symbol}] "
            f"가격: {self.state.last_price:,.2f} | "
            f"모멘텀: {self.state.price_momentum*100:+.2f}% | "
            f"불균형: {self.state.bid_ask_imbalance:+.3f} | "
            f"1분거래량: {self.state.recent_volume_1m:.2f} | "
            f"대형거래: {self.state.large_trade_count}건"
        )
