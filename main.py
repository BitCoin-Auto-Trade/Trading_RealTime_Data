"""
비트코인 선물 자동매매 봇

실시간 코인 데이터 수집 및 분석을 통한 자동 매매 시스템입니다.

주요 기능:
- 실시간 데이터 수집 및 검증
- 시장 상태 실시간 추적
- 고속 인메모리 저장소
- Auto Reconnection
- 체계적인 모니터링
"""

import asyncio
from typing import Optional, Dict, Any

from config.settings import Settings
from core.data_pipeline import DataPipeline
from core.signal_engine_v1 import SignalEngine
from core.market_state_manager import MarketState
from core.data_reconciliation import DataReconciliation
from data_collector.data_normalizer import NormalizedTrade, NormalizedOrderBook
from utils.logger_utils import setup_logger


class TradingBot:
    """
    비트코인 선물 자동매매 봇

    실시간 데이터 수집 → 검증 → 정규화 → 시그널 생성 → 주문 실행
    """

    def __init__(self, symbol: Optional[str] = None):
        """
        Args:
            symbol: 거래 심볼 (기본값: Settings에서 로드)
        """
        self.symbol = symbol or Settings.trading.default_symbol
        self.logger = setup_logger("trading_bot")

        # 데이터 파이프라인
        self.pipeline = DataPipeline(
            symbol=symbol,
            on_state_update=self.on_state_update
        )

        # 시그널 엔진 (기존 로직 유지)
        self.signal_engine = SignalEngine()

        # 데이터 검증 레이어 (WebSocket vs REST API)
        self.reconciliation = DataReconciliation(
            symbol=self.symbol,
            reconciliation_interval=60  # 1분마다 검증
        )

        # 포지션 상태
        self.current_position: Optional[str] = None  # None | "LONG" | "SHORT"

        self.logger.info(f"TradingBot initialized for {self.symbol}")

    async def on_state_update(
        self,
        data_type: str,
        data,
        state: MarketState
    ):
        """
        파이프라인에서 상태 업데이트 콜백

        Args:
            data_type: "trade" | "orderbook"
            data: NormalizedTrade | NormalizedOrderBook
            state: 현재 시장 상태
        """
        signal = None

        if data_type == "trade":
            # WebSocket 가격을 검증 레이어에 업데이트
            self.reconciliation.update_ws_price(data.price)

            # 기존 시그널 엔진과 통합
            # (기존 SignalEngine은 Trade 객체를 받으므로 호환성 유지)
            signal = self.signal_engine.update_trade(self._to_legacy_trade(data))

        elif data_type == "orderbook":
            # 호가창 기반 시그널 (추가 구현 가능)
            signal = self._check_orderbook_signal(data, state)

        # 시그널 처리
        if signal and self.current_position is None:
            await self._handle_entry_signal(signal, state)

        # 포지션 청산 체크
        if self.current_position:
            await self._check_exit_signal(state)

    async def _handle_entry_signal(self, signal: str, state: MarketState):
        """진입 시그널 처리"""
        self.logger.info("=" * 60)
        self.logger.info(f"🎯 {signal} 진입 시그널 발생")
        self.logger.info(f"가격: {state.last_price:,.2f}")
        self.logger.info(f"모멘텀: {state.price_momentum*100:+.2f}%")
        self.logger.info(f"불균형: {state.bid_ask_imbalance:+.3f}")
        self.logger.info(f"1분거래량: {state.recent_volume_1m:.2f}")
        self.logger.info(f"대형거래: {state.large_trade_count}건")
        self.logger.info("=" * 60)

        # ⚠️ 주문 실행 전 가격 재검증 (REST API)
        is_valid, rest_price = await self.reconciliation.verify_before_order(
            state.last_price
        )

        if not is_valid:
            self.logger.error(
                f"❌ 주문 취소: 가격 검증 실패 "
                f"(WS: {state.last_price:,.2f}, REST: {rest_price:,.2f})"
            )
            return

        self.logger.info(f"✅ 가격 검증 완료: {rest_price:,.2f}")

        # TODO: OrderExecutor로 주문 실행 (rest_price 사용)
        self.current_position = signal

    async def _check_exit_signal(self, state: MarketState):
        """청산 시그널 체크"""
        # 간단한 청산 로직 (향후 개선)
        should_exit = False

        if self.current_position == "LONG":
            # 롱 포지션: 호가 불균형이 매도로 반전
            if state.bid_ask_imbalance < -0.3:
                should_exit = True
                reason = "호가 매도 압력"

            # 가격 모멘텀 반전
            elif state.price_momentum < -0.002:  # -0.2%
                should_exit = True
                reason = "가격 하락 전환"

        elif self.current_position == "SHORT":
            # 숏 포지션: 호가 불균형이 매수로 반전
            if state.bid_ask_imbalance > 0.3:
                should_exit = True
                reason = "호가 매수 압력"

            # 가격 모멘텀 반전
            elif state.price_momentum > 0.002:  # +0.2%
                should_exit = True
                reason = "가격 상승 전환"

        if should_exit:
            self.logger.info("=" * 60)
            self.logger.info(f"🛑 {self.current_position} 청산 시그널")
            self.logger.info(f"사유: {reason}")
            self.logger.info(f"가격: {state.last_price:,.2f}")
            self.logger.info("=" * 60)

            # TODO: OrderExecutor로 청산 실행
            self.current_position = None

    def _check_orderbook_signal(
        self,
        orderbook: NormalizedOrderBook,
        state: MarketState
    ) -> Optional[str]:
        """호가창 기반 시그널 (추가 로직)"""
        # 극단적인 호가 불균형 감지
        if orderbook.imbalance > 0.7:  # 매수 70% 이상
            return "LONG"
        elif orderbook.imbalance < -0.7:  # 매도 70% 이상
            return "SHORT"

        return None

    def _to_legacy_trade(self, normalized_trade: NormalizedTrade):
        """NormalizedTrade → Trade 변환 (기존 코드 호환성)"""
        from models.trade import Trade

        return Trade(
            event_type="aggTrade",
            event_time=normalized_trade.timestamp,
            symbol=normalized_trade.symbol,
            aggregate_trade_id=normalized_trade.trade_id,
            price=str(normalized_trade.price),
            quantity=str(normalized_trade.quantity),
            first_trade_id=0,
            last_trade_id=0,
            trade_time=normalized_trade.timestamp,
            is_buyer_maker=normalized_trade.is_buyer_maker
        )

    async def start(self):
        """봇 시작"""
        self.logger.info("=" * 60)
        self.logger.info("🚀 Trading Bot Starting")
        self.logger.info(f"Symbol: {self.symbol}")
        self.logger.info(f"Leverage: {Settings.trading.leverage}x")
        self.logger.info(f"Position Size: {Settings.trading.position_size:,.0f}")
        self.logger.info("=" * 60)

        # 데이터 검증 레이어 시작
        await self.reconciliation.start()

        await self.pipeline.start()

    async def stop(self):
        """봇 종료"""
        self.logger.info("=" * 60)
        self.logger.info("🛑 Trading Bot Stopping")

        # 검증 통계 출력
        stats = self.reconciliation.get_stats()
        self.logger.info(f"Reconciliation Stats: {stats}")

        self.logger.info("=" * 60)

        await self.reconciliation.stop()
        await self.pipeline.stop()

    def get_stats(self) -> Dict[str, Any]:
        """
        통계 조회

        Returns:
            dict: 봇 상태, 시장 상태, 저장소 통계 등
        """
        return {
            "current_position": self.current_position,
            "market_state": self.pipeline.get_current_state(),
            "features": self.pipeline.get_features(),
            "storage": self.pipeline.get_storage_stats(),
            "validation": self.pipeline.get_validation_stats(),
            "reconciliation": self.reconciliation.get_stats()
        }

    def __repr__(self) -> str:
        return (
            f"TradingBot(symbol={self.symbol}, "
            f"position={self.current_position})"
        )


async def main():
    """메인 실행 함수"""
    # 설정 요약 출력
    print("=" * 60)
    print("Trading Bot Configuration")
    print("=" * 60)
    for key, value in Settings.get_summary().items():
        print(f"{key}: {value}")
    print("=" * 60)

    bot = TradingBot()

    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n사용자 중단")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
