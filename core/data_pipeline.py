"""
데이터 파이프라인 - 전체 플로우 통합

WebSocket → Validator → Normalizer → Storage → StateManager → SignalEngine
"""

import asyncio
from typing import Callable, Optional, Dict, Any

from config.settings import Settings
from data_collector.websocket_connector import WebSocketConnector
from data_collector.data_validator import DataValidator
from data_collector.data_normalizer import DataNormalizer
from core.market_state_manager import MarketStateManager
from storage.hot_storage import HotStorage
from models.order_book import OrderBook
from models.trade import Trade
from utils.logger_utils import setup_logger


class DataPipeline:
    """
    실시간 데이터 처리 파이프라인

    플로우:
        WebSocket → Validator → Normalizer → Storage → StateManager → Callback

    각 단계:
        1. WebSocket: 바이낸스에서 실시간 데이터 수신
        2. Validator: 데이터 품질 검증 (중복, NULL, 순서)
        3. Normalizer: 데이터 정규화 및 지표 계산
        4. Storage: 고속 인메모리 저장
        5. StateManager: 시장 상태 업데이트
        6. Callback: SignalEngine 등에 전달
    """

    def __init__(
        self,
        symbol: Optional[str] = None,
        on_state_update: Optional[Callable] = None
    ):
        """
        Args:
            symbol: 거래 심볼 (기본값: Settings에서 로드)
            on_state_update: 상태 업데이트 콜백 함수
        """
        self.symbol = (symbol or Settings.trading.default_symbol).lower()
        self.logger = setup_logger(f"pipeline_{self.symbol}")
        self.on_state_update = on_state_update

        # 설정 로드
        cfg_data = Settings.data
        cfg_trading = Settings.trading
        cfg_perf = Settings.performance

        # 컴포넌트 초기화
        self.logger.info(f"Initializing data pipeline for {self.symbol}...")

        # Connection
        self.websocket = WebSocketConnector(
            symbols={self.symbol},
            streams=cfg_data.default_streams
        )

        # Data Processing
        self.validator = DataValidator(expected_symbols={self.symbol.upper()})
        self.normalizer = DataNormalizer(
            large_trade_threshold=cfg_data.large_trade_threshold_usdt,
            orderbook_depth=cfg_data.orderbook_depth
        )

        # Storage & State
        self.storage = HotStorage(
            symbol=self.symbol.upper(),
            max_trades=cfg_data.hot_storage_max_trades,
            max_orderbooks=cfg_data.hot_storage_max_orderbooks,
            ttl_seconds=cfg_data.hot_storage_ttl_sec
        )
        self.state_manager = MarketStateManager(symbol=self.symbol.upper())

        # 통계
        self.processed_trades = 0
        self.processed_orderbooks = 0
        self.validation_errors = 0

        self.logger.info("Data pipeline initialized successfully")

    async def on_message(self, data_type: str, data):
        """
        WebSocket 메시지 핸들러

        Args:
            data_type: "trade" 또는 "orderbook"
            data: Trade 또는 OrderBook 객체
        """
        try:
            if data_type == "trade":
                await self._process_trade(data)
            elif data_type == "orderbook":
                await self._process_orderbook(data)
            else:
                self.logger.warning(f"Unknown data type: {data_type}")

        except Exception as e:
            self.logger.error(f"Error processing {data_type}: {e}", exc_info=True)

    async def _process_trade(self, trade: Trade):
        """체결 데이터 처리 파이프라인"""
        # 1. 검증
        validation_result = self.validator.validate_trade(trade)
        if not validation_result.is_valid:
            self.validation_errors += 1
            self.logger.warning(
                f"Trade validation failed: {validation_result.error_message}"
            )
            return

        # 2. 정규화
        normalized_trade = self.normalizer.normalize_trade(trade)

        # 3. 저장
        self.storage.add_trade(normalized_trade)

        # 4. 상태 업데이트
        self.state_manager.update_from_trade(normalized_trade)

        # 5. 콜백 호출 (SignalEngine 등)
        if self.on_state_update:
            await self.on_state_update(
                "trade",
                normalized_trade,
                self.state_manager.get_current_state()
            )

        self.processed_trades += 1

        # 주기적으로 통계 로깅
        if self.processed_trades % Settings.performance.stats_log_interval_trades == 0:
            self._log_stats()

    async def _process_orderbook(self, orderbook: OrderBook):
        """호가창 데이터 처리 파이프라인"""
        # 1. 검증
        validation_result = self.validator.validate_orderbook(orderbook)
        if not validation_result.is_valid:
            self.validation_errors += 1
            self.logger.warning(
                f"Orderbook validation failed: {validation_result.error_message}"
            )
            return

        # 2. 정규화
        normalized_orderbook = self.normalizer.normalize_orderbook(orderbook)

        # 3. 저장
        self.storage.add_orderbook(normalized_orderbook)

        # 4. 상태 업데이트
        self.state_manager.update_from_orderbook(normalized_orderbook)

        # 5. 콜백 호출
        if self.on_state_update:
            await self.on_state_update(
                "orderbook",
                normalized_orderbook,
                self.state_manager.get_current_state()
            )

        self.processed_orderbooks += 1

        # 주기적으로 상태 로깅
        if self.processed_orderbooks % Settings.performance.stats_log_interval_orderbooks == 0:
            self.state_manager.log_state()

    async def start(self):
        """파이프라인 시작"""
        self.logger.info(f"Starting data pipeline for {self.symbol}...")
        await self.websocket.start(self.on_message)

    async def stop(self):
        """파이프라인 종료"""
        self.logger.info(f"Stopping data pipeline for {self.symbol}...")
        await self.websocket.stop()
        self._log_final_stats()

    def get_current_state(self):
        """현재 시장 상태 반환"""
        return self.state_manager.get_current_state()

    def get_features(self):
        """시그널 생성용 특징 반환"""
        return self.state_manager.get_features()

    def get_storage_stats(self) -> Dict[str, Any]:
        """저장소 통계 반환"""
        return self.storage.get_stats()

    def get_validation_stats(self) -> Dict[str, Any]:
        """검증 통계 반환"""
        return self.validator.get_stats()

    def __repr__(self) -> str:
        return (
            f"DataPipeline(symbol={self.symbol}, "
            f"trades={self.processed_trades}, "
            f"orderbooks={self.processed_orderbooks})"
        )

    def _log_stats(self):
        """통계 로깅"""
        self.logger.info(
            f"[STATS] Trades: {self.processed_trades} | "
            f"Orderbooks: {self.processed_orderbooks} | "
            f"Validation errors: {self.validation_errors} | "
            f"Error rate: {self.validator.get_error_rate():.3%}"
        )

    def _log_final_stats(self):
        """최종 통계 로깅"""
        self.logger.info("=" * 60)
        self.logger.info("PIPELINE FINAL STATISTICS")
        self.logger.info("=" * 60)
        self.logger.info(f"Symbol: {self.symbol}")
        self.logger.info(f"Processed Trades: {self.processed_trades}")
        self.logger.info(f"Processed Orderbooks: {self.processed_orderbooks}")
        self.logger.info(f"Validation Errors: {self.validation_errors}")

        self.logger.info("\nValidation Stats:")
        for key, value in self.validator.get_stats().items():
            self.logger.info(f"  {key}: {value}")

        self.logger.info("\nStorage Stats:")
        for key, value in self.storage.get_stats().items():
            self.logger.info(f"  {key}: {value}")

        self.logger.info("\nWebSocket Stats:")
        for key, value in self.websocket.get_stats().items():
            self.logger.info(f"  {key}: {value}")

        self.logger.info("=" * 60)


async def main():
    """테스트용 메인"""
    async def on_update(data_type, data, state):
        """상태 업데이트 콜백"""
        if data_type == "trade" and data.is_large_trade:
            print(f"[대형거래] {data.side} {data.amount_usdt:,.0f} USDT @ {data.price:,.2f}")

    pipeline = DataPipeline(symbol="BTCUSDT", on_state_update=on_update)

    try:
        await pipeline.start()
    except KeyboardInterrupt:
        print("\nStopping pipeline...")
    finally:
        await pipeline.stop()


if __name__ == "__main__":
    asyncio.run(main())
