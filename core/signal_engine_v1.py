# core/signal_engine.py

import time
from collections import deque
from typing import Optional
from models.order_book import OrderBook
from models.trade import Trade
from config.settings import Settings


class SignalEngine:
    
    def __init__(self):
        # 설정
        self.volume_spike_window = Settings.VOLUME_SPIKE_WINDOW
        self.volume_spike_baseline = Settings.VOLUME_SPIKE_BASELINE
        self.volume_spike_ratio = Settings.VOLUME_SPIKE_RATIO
        self.min_trade_amount = Settings.MIN_TRADE_AMOUNT
        self.price_change_window = Settings.PRICE_CHANGE_WINDOW
        self.price_change_threshold = Settings.PRICE_CHANGE_THRESHOLD
        self.imbalance_threshold = Settings.IMBALANCE_THRESHOLD
        
        # 데이터 저장
        self.trade_history = deque(maxlen=5000)  # (timestamp, amount_usdt, price)
        self.last_imbalance = 0.5  # 마지막 호가 불균형
    
    def update_trade(self, trade: Trade):
        """체결 저장"""
        timestamp = trade.trade_time / 1000
        price = float(trade.price)
        quantity = float(trade.quantity)
        amount_usdt = price * quantity
        
        if amount_usdt >= self.min_trade_amount:
            self.trade_history.append((timestamp, amount_usdt, price))
    
    def update_orderbook(self, orderbook: OrderBook) -> Optional[str]:
        """시그널 생성"""
        # 호가 불균형
        bid_volume = sum(float(b[1]) for b in orderbook.bids[:5])
        ask_volume = sum(float(a[1]) for a in orderbook.asks[:5])
        total = bid_volume + ask_volume
        
        if total == 0:
            return None
        
        imbalance = bid_volume / total
        self.last_imbalance = imbalance
        
        # 3가지 조건 체크
        volume_spike = self._check_volume_spike()
        price_direction = self._check_price_change()
        
        # 둘 다 충족 + 호가 방향 일치
        if volume_spike and price_direction:
            # LONG: 가격 급등 + 매수 호가 쏠림
            if price_direction == "UP" and imbalance >= self.imbalance_threshold:
                return "LONG"
            # SHORT: 가격 급락 + 매도 호가 쏠림
            elif price_direction == "DOWN" and imbalance <= (1 - self.imbalance_threshold):
                return "SHORT"
        
        return None
    
    def _check_volume_spike(self) -> bool:
        """체결량 폭증"""
        if len(self.trade_history) < 2:
            return False
        
        now = time.time()
        
        # 최근 2초 거래량
        recent = sum(
            amount for ts, amount, _ in self.trade_history
            if now - ts <= self.volume_spike_window
        )
        
        # 3시간 평균
        baseline_start = now - self.volume_spike_baseline - self.volume_spike_window
        baseline_end = now - self.volume_spike_window
        baseline = sum(
            amount for ts, amount, _ in self.trade_history
            if baseline_start <= ts < baseline_end
        )
        
        if baseline == 0:
            return False
        
        recent_per_sec = recent / self.volume_spike_window
        baseline_per_sec = baseline / self.volume_spike_baseline
        
        return (recent_per_sec / baseline_per_sec) >= self.volume_spike_ratio
    
    def _check_price_change(self) -> Optional[str]:
        """가격 급변 (2초 내 0.3% 이상)"""
        if len(self.trade_history) < 2:
            return None
        
        now = time.time()
        
        # 최근 2초 내 가격들
        recent_prices = [
            price for ts, _, price in self.trade_history
            if now - ts <= self.price_change_window
        ]
        
        if len(recent_prices) < 2:
            return None
        
        start_price = recent_prices[0]
        end_price = recent_prices[-1]
        change = (end_price - start_price) / start_price
        
        if change >= self.price_change_threshold:
            return "UP"
        elif change <= -self.price_change_threshold:
            return "DOWN"
        
        return None
    
    def check_exit_signal(self, market_state, position_side: str) -> bool:
        """청산"""
        if position_side == "LONG" and market_state.imbalance < 0.5:
            return True
        elif position_side == "SHORT" and market_state.imbalance > 0.5:
            return True
        return False