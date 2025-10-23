"""
WebSocket 연결 관리

바이낸스 선물 WebSocket 연결을 관리하는 모듈입니다.
Auto Reconnection, Health Monitoring, Multi-stream을 지원합니다.
"""

import asyncio
import json
import time
import websockets
from typing import Callable, Optional, Set, Dict
from enum import Enum

from config.settings import Settings
from utils.logger_utils import setup_logger
from data_collector.data_parser import DataParser


class ConnectionState(Enum):
    """WebSocket 연결 상태"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class WebSocketConnector:
    """
    바이낸스 선물 WebSocket 연결 관리자

    주요 기능:
    - Auto Reconnection with Exponential Backoff
    - Connection Health Monitoring (Ping/Pong)
    - Message Buffer for reliability
    - Multi-symbol, Multi-stream support
    - Comprehensive error handling

    사용 예:
        connector = WebSocketConnector(symbols={"btcusdt"})
        await connector.start(on_message_callback)
    """

    def __init__(
        self,
        symbols: Optional[Set[str]] = None,
        streams: Optional[Set[str]] = None,
        max_reconnect_attempts: Optional[int] = None,
        initial_backoff: Optional[float] = None,
        max_backoff: Optional[float] = None,
        ping_interval: Optional[float] = None,
        ping_timeout: Optional[float] = None
    ):
        """
        Args:
            symbols: 거래 심볼 집합 (기본: {"btcusdt"})
            streams: 스트림 타입 집합 (기본: {"depth", "aggTrade"})
            max_reconnect_attempts: 최대 재연결 시도 횟수
            initial_backoff: 초기 backoff 시간(초)
            max_backoff: 최대 backoff 시간(초)
            ping_interval: Ping 전송 간격(초)
            ping_timeout: Ping 타임아웃(초)
        """
        # 설정 로드 (파라미터 우선, 없으면 Settings 사용)
        cfg = Settings.data

        self.symbols = symbols or {"btcusdt"}
        self.streams = streams or cfg.default_streams
        self.logger = setup_logger("websocket")

        # 재연결 설정
        self.max_reconnect_attempts = max_reconnect_attempts or cfg.ws_reconnect_max_attempts
        self.initial_backoff = initial_backoff or cfg.ws_initial_backoff_sec
        self.max_backoff = max_backoff or cfg.ws_max_backoff_sec
        self.current_backoff = self.initial_backoff
        self.reconnect_count = 0

        # Health check 설정
        self.ping_interval = ping_interval or cfg.ws_ping_interval_sec
        self.ping_timeout = ping_timeout or cfg.ws_ping_timeout_sec
        self.last_message_time = 0.0
        self.last_pong_time = 0.0

        # 연결 상태
        self.state = ConnectionState.DISCONNECTED
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.start_time = 0.0

        # 메시지 처리
        self.parser = DataParser()
        self.message_buffer: asyncio.Queue = asyncio.Queue(
            maxsize=Settings.performance.message_buffer_size
        )

        # 통계
        self.trade_count = 0
        self.orderbook_count = 0
        self.total_messages = 0
        self.error_count = 0

        # URL 생성
        self.url = self._build_url()

    def _build_url(self) -> str:
        """Multi-stream WebSocket URL 생성"""
        stream_names = []
        for symbol in self.symbols:
            for stream in self.streams:
                stream_names.append(f"{symbol}@{stream}")

        streams_param = "/".join(stream_names)
        url = f"wss://fstream.binance.com/stream?streams={streams_param}"
        self.logger.info(f"WebSocket URL: {url}")
        return url

    async def _connect(self) -> bool:
        """WebSocket 연결"""
        try:
            self.state = ConnectionState.CONNECTING
            self.logger.info(f"Connecting to {self.url}...")

            self.websocket = await websockets.connect(
                self.url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout
            )

            self.state = ConnectionState.CONNECTED
            self.start_time = time.time()
            self.last_message_time = time.time()
            self.last_pong_time = time.time()
            self.current_backoff = self.initial_backoff  # 연결 성공 시 backoff 리셋
            self.reconnect_count = 0

            self.logger.info("WebSocket connected successfully")
            return True

        except Exception as e:
            self.state = ConnectionState.FAILED
            self.logger.error(f"Connection failed: {e}")
            return False

    async def _reconnect(self) -> bool:
        """재연결 (Exponential Backoff)"""
        if self.reconnect_count >= self.max_reconnect_attempts:
            self.logger.error(
                f"Max reconnect attempts ({self.max_reconnect_attempts}) reached"
            )
            self.state = ConnectionState.FAILED
            return False

        self.state = ConnectionState.RECONNECTING
        self.reconnect_count += 1

        self.logger.warning(
            f"Reconnecting (attempt {self.reconnect_count}/{self.max_reconnect_attempts}) "
            f"in {self.current_backoff:.1f}s..."
        )

        await asyncio.sleep(self.current_backoff)

        # Exponential backoff
        self.current_backoff = min(self.current_backoff * 2, self.max_backoff)

        return await self._connect()

    async def _health_check(self):
        """연결 상태 모니터링"""
        while self.running:
            await asyncio.sleep(5)  # 5초마다 체크

            if self.state != ConnectionState.CONNECTED:
                continue

            now = time.time()

            # 메시지 수신 확인 (60초 이상 메시지 없으면 재연결)
            if now - self.last_message_time > 60:
                self.logger.warning(
                    f"No message received for {now - self.last_message_time:.1f}s. "
                    "Triggering reconnection..."
                )
                await self._trigger_reconnect()

    async def _trigger_reconnect(self):
        """재연결 트리거"""
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                self.logger.error(f"Error closing websocket: {e}")

        await self._reconnect()

    async def _receive_messages(self, on_message: Callable):
        """메시지 수신 루프"""
        while self.running:
            try:
                if self.state != ConnectionState.CONNECTED or not self.websocket:
                    await asyncio.sleep(1)
                    continue

                # 24시간 제한으로 재연결
                if (time.time() - self.start_time) / 3600 >= 23.5:
                    self.logger.info("24-hour limit reached. Reconnecting...")
                    await self._trigger_reconnect()
                    continue

                # 메시지 수신
                try:
                    message = await asyncio.wait_for(
                        self.websocket.recv(),
                        timeout=30.0
                    )
                    self.last_message_time = time.time()
                    self.total_messages += 1

                    # 메시지 처리
                    await self._process_message(message, on_message)

                except asyncio.TimeoutError:
                    self.logger.warning("Message receive timeout")
                    continue

                except websockets.exceptions.ConnectionClosed as e:
                    self.logger.warning(f"Connection closed: {e}")
                    await self._trigger_reconnect()

            except Exception as e:
                self.logger.error(f"Error in receive loop: {e}")
                self.error_count += 1
                await asyncio.sleep(1)

    async def _process_message(self, message: str, on_message: Callable):
        """메시지 파싱 및 콜백 호출"""
        try:
            data = json.loads(message)

            if "stream" not in data or "data" not in data:
                self.logger.debug(f"Unknown message format: {message[:100]}")
                return

            stream_name = data["stream"]
            raw_data = data["data"]

            # 스트림별로 파싱
            if "@depth" in stream_name:
                parsed = self.parser.parse_order_book(raw_data)
                self.orderbook_count += 1
                await on_message("orderbook", parsed)

            elif "@aggTrade" in stream_name:
                parsed = self.parser.parse_trade(raw_data)
                self.trade_count += 1
                await on_message("trade", parsed)

            else:
                self.logger.debug(f"Unknown stream: {stream_name}")

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            self.error_count += 1
        except Exception as e:
            self.logger.error(f"Message processing error: {e}")
            self.error_count += 1

    async def start(self, on_message: Callable):
        """WebSocket 시작"""
        self.logger.info("Starting WebSocket connector...")
        self.running = True

        # 초기 연결
        if not await self._connect():
            self.logger.error("Initial connection failed")
            return

        # 백그라운드 태스크 시작
        tasks = [
            asyncio.create_task(self._receive_messages(on_message)),
            asyncio.create_task(self._health_check())
        ]

        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            self.logger.error(f"Error in background tasks: {e}")
        finally:
            await self.stop()

    async def stop(self):
        """WebSocket 종료"""
        self.logger.info("Stopping WebSocket connector...")
        self.running = False
        self.state = ConnectionState.DISCONNECTED

        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as e:
                self.logger.error(f"Error closing websocket: {e}")

        self.logger.info(
            f"WebSocket stopped | "
            f"Total messages: {self.total_messages} | "
            f"Trades: {self.trade_count} | "
            f"Orderbooks: {self.orderbook_count} | "
            f"Errors: {self.error_count} | "
            f"Reconnects: {self.reconnect_count}"
        )

    def get_state(self) -> ConnectionState:
        """현재 연결 상태 반환"""
        return self.state

    def is_connected(self) -> bool:
        """연결 여부 확인"""
        return self.state == ConnectionState.CONNECTED

    def get_stats(self) -> dict:
        """통계 반환"""
        return {
            "state": self.state.value,
            "total_messages": self.total_messages,
            "trade_count": self.trade_count,
            "orderbook_count": self.orderbook_count,
            "error_count": self.error_count,
            "reconnect_count": self.reconnect_count,
            "uptime_seconds": time.time() - self.start_time if self.start_time > 0 else 0,
            "last_message_age": time.time() - self.last_message_time if self.last_message_time > 0 else 0
        }
