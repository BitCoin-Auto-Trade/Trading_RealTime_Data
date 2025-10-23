"""데이터 품질 검증 모듈"""

from typing import Optional, Set
from dataclasses import dataclass
from enum import Enum

from models.order_book import OrderBook
from models.trade import Trade
from utils.logger_utils import setup_logger


class ValidationErrorType(Enum):
    """검증 에러 타입"""
    NULL_VALUE = "null_value"
    NEGATIVE_PRICE = "negative_price"
    NEGATIVE_QUANTITY = "negative_quantity"
    INVALID_TIMESTAMP = "invalid_timestamp"
    OUT_OF_ORDER = "out_of_order"
    DUPLICATE = "duplicate"
    EMPTY_ORDERBOOK = "empty_orderbook"
    INVALID_SYMBOL = "invalid_symbol"


@dataclass
class ValidationResult:
    """검증 결과"""
    is_valid: bool
    error_type: Optional[ValidationErrorType] = None
    error_message: Optional[str] = None


class DataValidator:
    """실시간 데이터 품질 검증"""

    def __init__(self, expected_symbols: Set[str] = None):
        self.logger = setup_logger("data_validator")
        self.expected_symbols = expected_symbols or {"BTCUSDT"}

        # 중복 체크용 (최근 1000개 ID 저장)
        self.recent_trade_ids: Set[int] = set()
        self.max_trade_ids = 1000

        # 순서 체크용 (마지막 타임스탬프)
        self.last_trade_timestamp: int = 0
        self.last_orderbook_timestamp: int = 0

        # 통계
        self.total_validated = 0
        self.total_errors = 0
        self.error_counts = {error_type: 0 for error_type in ValidationErrorType}

    def validate_trade(self, trade: Trade) -> ValidationResult:
        """체결 데이터 검증"""
        self.total_validated += 1

        # 1. Null 체크
        if not trade.price or not trade.quantity:
            return self._record_error(
                ValidationErrorType.NULL_VALUE,
                f"Price or Quantity is null: {trade}"
            )

        # 2. 가격/수량 음수 체크
        try:
            price = float(trade.price)
            quantity = float(trade.quantity)

            if price <= 0:
                return self._record_error(
                    ValidationErrorType.NEGATIVE_PRICE,
                    f"Invalid price: {price}"
                )

            if quantity <= 0:
                return self._record_error(
                    ValidationErrorType.NEGATIVE_QUANTITY,
                    f"Invalid quantity: {quantity}"
                )
        except (ValueError, TypeError) as e:
            return self._record_error(
                ValidationErrorType.NULL_VALUE,
                f"Cannot convert price/quantity to float: {e}"
            )

        # 3. 타임스탬프 검증
        if trade.trade_time <= 0:
            return self._record_error(
                ValidationErrorType.INVALID_TIMESTAMP,
                f"Invalid timestamp: {trade.trade_time}"
            )

        # 4. 심볼 검증
        if trade.symbol not in self.expected_symbols:
            return self._record_error(
                ValidationErrorType.INVALID_SYMBOL,
                f"Unexpected symbol: {trade.symbol}"
            )

        # 5. 중복 체크
        if self.is_duplicate_trade(trade.aggregate_trade_id):
            return self._record_error(
                ValidationErrorType.DUPLICATE,
                f"Duplicate trade ID: {trade.aggregate_trade_id}"
            )

        # 6. 순서 체크 (경고만, 실패는 아님)
        if self.is_out_of_order_trade(trade.trade_time):
            self.logger.warning(
                f"Out of order trade: current={trade.trade_time}, "
                f"last={self.last_trade_timestamp}"
            )
            # 순서 역전은 에러가 아니라 경고만 (네트워크 지연 가능)

        # 검증 통과 - ID 저장 및 타임스탬프 업데이트
        self._add_trade_id(trade.aggregate_trade_id)
        self.last_trade_timestamp = max(self.last_trade_timestamp, trade.trade_time)

        return ValidationResult(is_valid=True)

    def validate_orderbook(self, orderbook: OrderBook) -> ValidationResult:
        """호가창 데이터 검증"""
        self.total_validated += 1

        # 1. Null 체크
        if not orderbook.bids or not orderbook.asks:
            return self._record_error(
                ValidationErrorType.EMPTY_ORDERBOOK,
                "Bids or Asks is empty"
            )

        # 2. 타임스탬프 검증
        if orderbook.event_time <= 0:
            return self._record_error(
                ValidationErrorType.INVALID_TIMESTAMP,
                f"Invalid timestamp: {orderbook.event_time}"
            )

        # 3. 심볼 검증
        if orderbook.symbol not in self.expected_symbols:
            return self._record_error(
                ValidationErrorType.INVALID_SYMBOL,
                f"Unexpected symbol: {orderbook.symbol}"
            )

        # 4. 호가 가격/수량 검증
        try:
            for bid in orderbook.bids[:5]:  # 상위 5개만 체크
                price, qty = float(bid[0]), float(bid[1])
                if price <= 0 or qty < 0:
                    return self._record_error(
                        ValidationErrorType.NEGATIVE_PRICE,
                        f"Invalid bid: price={price}, qty={qty}"
                    )

            for ask in orderbook.asks[:5]:  # 상위 5개만 체크
                price, qty = float(ask[0]), float(ask[1])
                if price <= 0 or qty < 0:
                    return self._record_error(
                        ValidationErrorType.NEGATIVE_PRICE,
                        f"Invalid ask: price={price}, qty={qty}"
                    )
        except (ValueError, TypeError, IndexError) as e:
            return self._record_error(
                ValidationErrorType.NULL_VALUE,
                f"Cannot parse orderbook: {e}"
            )

        # 5. 순서 체크 (경고만)
        if self.is_out_of_order_orderbook(orderbook.event_time):
            self.logger.warning(
                f"Out of order orderbook: current={orderbook.event_time}, "
                f"last={self.last_orderbook_timestamp}"
            )

        # 검증 통과
        self.last_orderbook_timestamp = max(
            self.last_orderbook_timestamp,
            orderbook.event_time
        )

        return ValidationResult(is_valid=True)

    def is_duplicate_trade(self, trade_id: int) -> bool:
        """중복 체결 체크"""
        return trade_id in self.recent_trade_ids

    def is_out_of_order_trade(self, timestamp: int) -> bool:
        """체결 순서 역전 체크"""
        return timestamp < self.last_trade_timestamp

    def is_out_of_order_orderbook(self, timestamp: int) -> bool:
        """호가창 순서 역전 체크"""
        return timestamp < self.last_orderbook_timestamp

    def _add_trade_id(self, trade_id: int):
        """Trade ID 저장 (중복 체크용)"""
        self.recent_trade_ids.add(trade_id)

        # 최대 개수 초과 시 오래된 것 제거
        if len(self.recent_trade_ids) > self.max_trade_ids:
            # Set에서 임의로 제거 (오래된 것이라고 보장은 없지만 근사치)
            self.recent_trade_ids.pop()

    def _record_error(
        self,
        error_type: ValidationErrorType,
        message: str
    ) -> ValidationResult:
        """에러 기록"""
        self.total_errors += 1
        self.error_counts[error_type] += 1
        self.logger.error(f"[{error_type.value}] {message}")

        return ValidationResult(
            is_valid=False,
            error_type=error_type,
            error_message=message
        )

    def get_error_rate(self) -> float:
        """에러율 계산"""
        if self.total_validated == 0:
            return 0.0
        return self.total_errors / self.total_validated

    def get_stats(self) -> dict:
        """검증 통계"""
        return {
            "total_validated": self.total_validated,
            "total_errors": self.total_errors,
            "error_rate": self.get_error_rate(),
            "error_counts": {
                error_type.value: count
                for error_type, count in self.error_counts.items()
                if count > 0
            }
        }

    def reset_stats(self):
        """통계 초기화"""
        self.total_validated = 0
        self.total_errors = 0
        self.error_counts = {error_type: 0 for error_type in ValidationErrorType}
        self.logger.info("Validation statistics reset")
