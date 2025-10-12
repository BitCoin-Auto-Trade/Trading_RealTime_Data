# core/signal_engine.py

import time
from collections import deque
from typing import Optional

from models.order_book import OrderBook
from utils.logger_utils import setup_logger
from models.trade import Trade
from config.settings import Settings

logger = setup_logger("signal_engine")

class SignalEngine:
    
    def __init__(self):
        self.min_trade_amount = Settings.MIN_TRADE_AMOUNT
        self.price_spike_window = Settings.PRICE_SPIKE_WINDOW
        self.price_spike_threshold = Settings.PRICE_SPIKE_THRESHOLD
        self.imbalance_threshold = Settings.IMBALANCE_THRESHOLD
        
        # (timestamp, amount_usdt, price)
        self.trade_history = deque(maxlen=1000)
    
    def update_trade(self, trade: Trade):
        """체결 저장"""
        timestamp = trade.trade_time / 1000
        price = float(trade.price)
        quantity = float(trade.quantity)
        amount_usdt = price * quantity
        
        if amount_usdt >= self.min_trade_amount:
            self.trade_history.append((timestamp, amount_usdt, price))
            logger.debug(f"[대형거래 저장] {amount_usdt:,.0f} USDT | "
                         f"가격: {price:.2f} | 수량: {quantity:.4f} | "
                         f"총 저장: {len(self.trade_history)}개")
        else:
            logger.debug(f"[소액거래 무시] {amount_usdt:,.0f} USDT (임계값: {self.min_trade_amount:,.0f})")

    def update_orderbook(self, orderbook: OrderBook) -> Optional[str]:
        """시그널 생성"""
        # 가격 급변 체크
        price_direction, price_change = self._check_price_change()
        
        if price_direction:
            logger.info("-"*60)
            logger.info(f"[가격 급변] {price_direction} {abs(price_change)*100:.2f}%")

            # LONG: 가격 급등
            if price_direction == "UP":
                logger.info("="*60)
                logger.info("LONG 시그널 (가격 급등)")
                logger.info("="*60)
                return "LONG"
            # SHORT: 가격 급락
            elif price_direction == "DOWN":
                logger.info("="*60)
                logger.info("SHORT 시그널 (가격 급락)")
                logger.info("="*60)
                return "SHORT"

            logger.info("-"*60)

        return None
    
    def _check_price_change(self) -> tuple[Optional[str], Optional[float]]:
        """5초 내 가격 변화"""
        if len(self.trade_history) < 2:
            logger.debug(f"[가격체크] 거래 데이터 부족 (현재: {len(self.trade_history)}개)")
            return None, None
        
        now = time.time()
        
        # 최근 5초 가격
        recent_prices = [
            price for ts, _, price in self.trade_history
            if now - ts <= self.price_spike_window
        ]
        
        if len(recent_prices) < 2:
            logger.debug(f"[가격체크] {self.price_spike_window}초 내 가격 데이터 부족 (현재: {len(recent_prices)}개)")
            return None, None
        
        start_price = recent_prices[0]
        end_price = recent_prices[-1]
        change = (end_price - start_price) / start_price

        logger.debug(f"[가격체크] {len(recent_prices)}개 데이터 | "
                     f"시작: {start_price:.2f} → 끝: {end_price:.2f} | "
                     f"변화: {change*100:+.3f}% (임계값: ±{self.price_spike_threshold*100}%)")

        if change >= self.price_spike_threshold:
            return "UP", change
        elif change <= -self.price_spike_threshold:
            return "DOWN", change
        
        return None, change
    
    def check_exit_signal(self, market_state, position_side: str) -> bool:
        """청산"""
        if position_side == "LONG" and market_state.imbalance < 0.5:
            return True
        elif position_side == "SHORT" and market_state.imbalance > 0.5:
            return True
        return False