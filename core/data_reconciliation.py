"""
REST API 데이터 검증 레이어

WebSocket 데이터를 REST API로 주기적으로 검증합니다.
"""

import asyncio
import time
from typing import Optional, Dict, Any
import aiohttp

from config.settings import Settings
from utils.logger_utils import setup_logger


class DataReconciliation:
    """
    WebSocket 데이터 검증 및 복구

    주요 기능:
    - WebSocket 데이터 신뢰성 검증
    - REST API로 주기적 검증 (1-5분 간격)
    - 데이터 불일치 감지 및 경고
    - 누락된 데이터 복구
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        reconciliation_interval: int = 60  # 1분
    ):
        self.symbol = symbol
        self.reconciliation_interval = reconciliation_interval
        self.logger = setup_logger("data_reconciliation")

        self.base_url = "https://fapi.binance.com"
        self.session: Optional[aiohttp.ClientSession] = None

        # 검증 통계
        self.total_checks = 0
        self.mismatch_count = 0
        self.last_rest_price: Optional[float] = None
        self.last_ws_price: Optional[float] = None

    async def start(self):
        """검증 시작"""
        self.session = aiohttp.ClientSession()
        self.logger.info(f"Data reconciliation started for {self.symbol}")

        # 백그라운드 검증 태스크
        asyncio.create_task(self._reconciliation_loop())

    async def stop(self):
        """검증 종료"""
        if self.session:
            await self.session.close()
        self.logger.info("Data reconciliation stopped")

    async def _reconciliation_loop(self):
        """주기적 검증 루프"""
        while True:
            try:
                await asyncio.sleep(self.reconciliation_interval)
                await self._check_data_integrity()
            except Exception as e:
                self.logger.error(f"Reconciliation error: {e}")

    async def _check_data_integrity(self):
        """데이터 무결성 검증"""
        try:
            # REST API로 최신 가격 조회
            rest_data = await self._fetch_rest_ticker()

            if not rest_data:
                self.logger.warning("Failed to fetch REST data")
                return

            rest_price = float(rest_data['lastPrice'])
            self.last_rest_price = rest_price
            self.total_checks += 1

            # WebSocket 가격과 비교 (있는 경우)
            if self.last_ws_price:
                price_diff_pct = abs(rest_price - self.last_ws_price) / rest_price

                # 0.1% 이상 차이 나면 경고
                if price_diff_pct > 0.001:
                    self.mismatch_count += 1
                    self.logger.warning(
                        f"⚠️  Price mismatch detected! "
                        f"REST: {rest_price:,.2f} | "
                        f"WS: {self.last_ws_price:,.2f} | "
                        f"Diff: {price_diff_pct*100:.3f}%"
                    )
                else:
                    self.logger.debug(
                        f"✅ Data consistent: REST={rest_price:,.2f}, "
                        f"WS={self.last_ws_price:,.2f}"
                    )

            # 통계 로깅
            if self.total_checks % 10 == 0:
                mismatch_rate = self.mismatch_count / self.total_checks * 100
                self.logger.info(
                    f"[Reconciliation Stats] "
                    f"Checks: {self.total_checks} | "
                    f"Mismatches: {self.mismatch_count} ({mismatch_rate:.2f}%)"
                )

        except Exception as e:
            self.logger.error(f"Integrity check error: {e}")

    async def _fetch_rest_ticker(self) -> Optional[Dict[str, Any]]:
        """REST API로 티커 정보 조회"""
        try:
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            params = {"symbol": self.symbol}

            async with self.session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    self.logger.error(f"REST API error: {resp.status}")
                    return None

        except asyncio.TimeoutError:
            self.logger.error("REST API timeout")
            return None
        except Exception as e:
            self.logger.error(f"REST API fetch error: {e}")
            return None

    def update_ws_price(self, price: float):
        """WebSocket 가격 업데이트"""
        self.last_ws_price = price

    async def verify_before_order(self, ws_price: float) -> tuple[bool, Optional[float]]:
        """
        주문 실행 전 가격 재확인

        Args:
            ws_price: WebSocket에서 받은 가격

        Returns:
            (검증 성공 여부, 최신 REST 가격)
        """
        rest_data = await self._fetch_rest_ticker()

        if not rest_data:
            self.logger.error("❌ Cannot verify price - REST API failed")
            return False, None

        rest_price = float(rest_data['lastPrice'])
        price_diff_pct = abs(rest_price - ws_price) / rest_price

        # 0.5% 이상 차이 나면 거부
        if price_diff_pct > 0.005:
            self.logger.error(
                f"❌ Price verification failed! "
                f"WS: {ws_price:,.2f} | REST: {rest_price:,.2f} | "
                f"Diff: {price_diff_pct*100:.3f}%"
            )
            return False, rest_price

        self.logger.info(
            f"✅ Price verified: {rest_price:,.2f} "
            f"(diff: {price_diff_pct*100:.3f}%)"
        )
        return True, rest_price

    def get_stats(self) -> Dict[str, Any]:
        """검증 통계 반환"""
        mismatch_rate = (
            self.mismatch_count / self.total_checks * 100
            if self.total_checks > 0
            else 0
        )

        return {
            "total_checks": self.total_checks,
            "mismatch_count": self.mismatch_count,
            "mismatch_rate": f"{mismatch_rate:.2f}%",
            "last_rest_price": self.last_rest_price,
            "last_ws_price": self.last_ws_price
        }
