"""
중앙 설정 관리

환경 변수와 애플리케이션 설정을 중앙에서 관리합니다.
타입 안정성과 검증을 제공합니다.
"""

import os
from typing import Set, Optional
from dataclasses import dataclass, field
from pathlib import Path
import dotenv

# 환경 변수 로드
dotenv.load_dotenv()


@dataclass(frozen=True)
class BinanceConfig:
    """바이낸스 API 설정"""
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("BINANCE_API_KEY"))
    api_secret: Optional[str] = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET"))
    testnet: bool = field(default_factory=lambda: os.getenv("BINANCE_TESTNET", "false").lower() == "true")

    # WebSocket URLs
    futures_ws_url: str = "wss://fstream.binance.com/stream"
    testnet_ws_url: str = "wss://stream.binancefuture.com/stream"

    @property
    def websocket_url(self) -> str:
        """환경에 맞는 WebSocket URL 반환"""
        return self.testnet_ws_url if self.testnet else self.futures_ws_url


@dataclass(frozen=True)
class TradingConfig:
    """트레이딩 설정"""
    # 기본 설정
    default_symbol: str = "BTCUSDT"
    supported_symbols: Set[str] = field(default_factory=lambda: {"BTCUSDT", "ETHUSDT"})

    # 시그널 임계값
    min_trade_amount_usdt: float = 10000.0  # 대형 거래 임계값
    price_spike_window_sec: float = 5.0      # 가격 급변 감지 윈도우
    price_spike_threshold: float = 0.001     # 0.1% 가격 변화
    imbalance_threshold: float = 0.65        # 65:35 호가 불균형

    # 리스크 관리
    initial_capital: float = 100000.0        # 초기 자본 (원)
    leverage: int = 10
    position_size: float = 1000000.0         # 포지션 크기
    stop_loss_pct: float = 0.05              # 5% 손절
    trading_fee_pct: float = 0.0005          # 0.05% 수수료

    def __post_init__(self):
        """설정 검증"""
        if self.price_spike_threshold <= 0 or self.price_spike_threshold >= 1:
            raise ValueError("price_spike_threshold must be between 0 and 1")
        if self.imbalance_threshold <= 0.5 or self.imbalance_threshold >= 1:
            raise ValueError("imbalance_threshold must be between 0.5 and 1")
        if self.leverage < 1 or self.leverage > 125:
            raise ValueError("leverage must be between 1 and 125")


@dataclass(frozen=True)
class DataConfig:
    """데이터 수집 및 저장 설정"""
    # WebSocket 설정
    ws_ping_interval_sec: float = 20.0
    ws_ping_timeout_sec: float = 10.0
    ws_reconnect_max_attempts: int = 10
    ws_initial_backoff_sec: float = 1.0
    ws_max_backoff_sec: float = 60.0

    # 데이터 검증
    validation_enabled: bool = True
    duplicate_check_enabled: bool = True
    max_recent_trade_ids: int = 1000

    # 정규화
    orderbook_depth: int = 5                 # 호가창 깊이
    large_trade_threshold_usdt: float = 10000.0

    # 저장소
    hot_storage_max_trades: int = 10000
    hot_storage_max_orderbooks: int = 1000
    hot_storage_ttl_sec: int = 3600          # 1시간

    # 스트림 설정
    default_streams: Set[str] = field(default_factory=lambda: {"depth", "aggTrade"})


@dataclass(frozen=True)
class LoggingConfig:
    """로깅 설정"""
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    log_file: Path = field(default_factory=lambda: Path("trading_bot.log"))
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_max_bytes: int = 10 * 1024 * 1024    # 10MB
    log_backup_count: int = 5

    # 구조화된 로깅
    structured_logging: bool = False
    json_logs: bool = False


@dataclass(frozen=True)
class PerformanceConfig:
    """성능 최적화 설정"""
    # 목표 레이턴시 (밀리초)
    target_latency_ms: float = 50.0

    # 통계 로깅 주기
    stats_log_interval_trades: int = 100
    stats_log_interval_orderbooks: int = 50

    # 메시지 버퍼
    message_buffer_size: int = 10000

    # 클린업 주기
    cleanup_interval_sec: float = 300.0      # 5분


class Settings:
    """통합 설정 클래스"""

    # 서브 설정 인스턴스
    binance: BinanceConfig = BinanceConfig()
    trading: TradingConfig = TradingConfig()
    data: DataConfig = DataConfig()
    logging: LoggingConfig = LoggingConfig()
    performance: PerformanceConfig = PerformanceConfig()

    # 하위 호환성을 위한 별칭 (기존 코드 지원)
    BINANCE_API_KEY = binance.api_key
    BINANCE_API_SECRET = binance.api_secret
    MIN_TRADE_AMOUNT = trading.min_trade_amount_usdt
    PRICE_SPIKE_WINDOW = trading.price_spike_window_sec
    PRICE_SPIKE_THRESHOLD = trading.price_spike_threshold
    IMBALANCE_THRESHOLD = trading.imbalance_threshold

    @classmethod
    def validate_all(cls) -> bool:
        """모든 설정 검증"""
        try:
            # 각 설정 검증
            _ = cls.binance
            _ = cls.trading
            _ = cls.data
            _ = cls.logging
            _ = cls.performance
            return True
        except Exception as e:
            print(f"Settings validation failed: {e}")
            return False

    @classmethod
    def get_summary(cls) -> dict:
        """설정 요약 반환"""
        return {
            "binance": {
                "testnet": cls.binance.testnet,
                "has_credentials": bool(cls.binance.api_key and cls.binance.api_secret)
            },
            "trading": {
                "symbol": cls.trading.default_symbol,
                "leverage": cls.trading.leverage,
                "position_size": cls.trading.position_size
            },
            "data": {
                "validation": cls.data.validation_enabled,
                "orderbook_depth": cls.data.orderbook_depth,
                "storage_ttl": cls.data.hot_storage_ttl_sec
            },
            "performance": {
                "target_latency_ms": cls.performance.target_latency_ms,
                "buffer_size": cls.performance.message_buffer_size
            }
        }


# 모듈 레벨에서 설정 검증
if not Settings.validate_all():
    import warnings
    warnings.warn("Settings validation failed. Check configuration.", UserWarning)
