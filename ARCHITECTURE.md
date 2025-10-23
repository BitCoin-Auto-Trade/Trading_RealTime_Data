# 실시간 코인 데이터 수집 아키텍처

## 1. 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Sources                              │
│          Binance Futures WebSocket (Multi-Stream)                │
│        - Order Book Depth (@depth)                               │
│        - Aggregate Trades (@aggTrade)                            │
│        - Klines (@kline)                                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Connection Layer                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ WebSocketConnector (Multi-Connection Pool)               │   │
│  │ - Connection Health Monitoring                           │   │
│  │ - Auto Reconnection with Exponential Backoff             │   │
│  │ - Message Queue Buffer                                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Data Pipeline                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Parser     │───▶│  Validator   │───▶│  Normalizer  │      │
│  │  (JSON→Obj)  │    │ (Data Check) │    │ (Transform)  │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Data Storage Layer                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  Hot Storage    │  │  Warm Storage   │  │  Cold Storage  │  │
│  │  (In-Memory)    │  │  (Time-Series)  │  │  (Archive)     │  │
│  │  - Recent Data  │  │  - InfluxDB     │  │  - Parquet     │  │
│  │  - Ring Buffer  │  │  - Last 7 days  │  │  - S3/Local    │  │
│  │  - Ultra Fast   │  │  - Analytics    │  │  - Historical  │  │
│  └─────────────────┘  └─────────────────┘  └────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Processing Layer                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Data Aggregator (Async Event Handlers)                  │   │
│  │  - Market State Manager                                  │   │
│  │  - Feature Calculator (실시간 지표 계산)                    │   │
│  │  - Signal Engine (진입/청산 시그널)                         │   │
│  └──────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Application Layer                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │Trading Engine│  │  Backtester  │  │  Dashboard   │          │
│  │  (Executor)  │  │  (Strategy)  │  │  (Monitor)   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘

                         ┌───────────────┐
                         │  Monitoring   │
                         │  & Alerting   │
                         │  (Prometheus) │
                         └───────────────┘
```

---

## 2. 핵심 컴포넌트 설계

### 2.1 Connection Layer

#### WebSocketConnector
**역할**: 안정적인 WebSocket 연결 관리

**주요 기능**:
- Multi-stream 지원 (복수 페어, 복수 데이터 타입)
- Connection Pool 관리
- Health Check (Ping/Pong, Heartbeat)
- Auto Reconnection (Exponential Backoff)
- Message Buffer (연결 끊김 시 데이터 손실 방지)

**구현 세부사항**:
```python
class WebSocketConnector:
    - connection_pool: Dict[str, WebSocketConnection]
    - message_buffer: asyncio.Queue(maxsize=10000)
    - health_monitor: ConnectionHealthMonitor
    - reconnection_strategy: ExponentialBackoff

    async def connect(symbol: str, streams: List[str])
    async def disconnect(symbol: str)
    async def subscribe(stream: str)
    async def unsubscribe(stream: str)
    async def health_check()
    async def reconnect(delay: float)
```

**메트릭**:
- Connection uptime
- Reconnection count
- Message throughput (msg/sec)
- Latency (WebSocket → Parser)

---

### 2.2 Data Pipeline

#### DataParser
**역할**: Raw JSON → Typed Objects

```python
class DataParser:
    def parse_orderbook(raw: dict) -> OrderBook
    def parse_trade(raw: dict) -> Trade
    def parse_kline(raw: dict) -> Kline
```

#### DataValidator
**역할**: 데이터 품질 검증

**검증 항목**:
- Null check
- Price/Quantity 음수 체크
- Timestamp 순서 검증 (순서 역전 탐지)
- Duplicate 제거
- Schema validation

```python
class DataValidator:
    def validate_orderbook(ob: OrderBook) -> ValidationResult
    def validate_trade(trade: Trade) -> ValidationResult
    def is_duplicate(data_id: str) -> bool
    def is_out_of_order(timestamp: int) -> bool
```

#### DataNormalizer
**역할**: 데이터 정규화 및 보강

```python
class DataNormalizer:
    def normalize_orderbook(ob: OrderBook) -> NormalizedOrderBook
        - Calculate bid-ask spread
        - Calculate total bid/ask volume
        - Calculate weighted mid price

    def normalize_trade(trade: Trade) -> NormalizedTrade
        - Add VWAP
        - Add cumulative volume
        - Add buy/sell pressure
```

---

### 2.3 Data Storage Layer

#### Hot Storage (In-Memory)
**목적**: 초저지연 데이터 접근 (Signal Engine용)

**구조**:
```python
class HotStorage:
    # 최근 N개 데이터만 보관 (Ring Buffer)
    recent_trades: deque(maxlen=1000)
    recent_orderbooks: deque(maxlen=100)

    # 집계된 상태
    current_market_state: MarketState
    features: Dict[str, float]  # VWAP, 호가압력, 거래량 등

    # 빠른 조회를 위한 인덱스
    trade_index_by_time: SortedDict
    orderbook_snapshot: Dict[float, float]  # price → quantity
```

**특징**:
- 모든 접근이 O(1) 또는 O(log N)
- Lock-free data structure 사용
- TTL 기반 자동 삭제

#### Warm Storage (Time-Series DB)
**목적**: 최근 데이터 분석 및 백테스팅

**선택지**:
1. **InfluxDB** (권장)
   - 시계열 데이터 특화
   - 빠른 쓰기 성능
   - Downsampling 지원

2. **TimescaleDB** (PostgreSQL 확장)
   - SQL 쿼리 가능
   - 복잡한 분석에 유리

**스키마 예시** (InfluxDB):
```
measurement: trades
tags: symbol, side (buy/sell)
fields: price, quantity, amount_usdt
timestamp: trade_time

measurement: orderbook
tags: symbol, side (bid/ask)
fields: best_bid, best_ask, spread, total_bid_volume, total_ask_volume, imbalance
timestamp: event_time
```

**보관 정책**:
- Raw data: 7일
- 1분 집계: 30일
- 1시간 집계: 1년

#### Cold Storage (Archive)
**목적**: 장기 보관 및 감사

**포맷**: Parquet (압축률 높고 분석 효율적)

**구조**:
```
data/
├── trades/
│   ├── 2025/
│   │   ├── 01/
│   │   │   ├── btcusdt_trades_20250101.parquet
│   │   │   └── btcusdt_trades_20250102.parquet
└── orderbook/
    └── ...
```

**압축 및 파티셔닝**:
- 일별 파티션
- Snappy 압축
- S3/Local FS

---

### 2.4 Processing Layer

#### MarketStateManager
**역할**: 시장 상태 실시간 추적

```python
@dataclass
class MarketState:
    timestamp: int
    symbol: str

    # 가격 정보
    last_price: float
    best_bid: float
    best_ask: float
    spread: float
    mid_price: float

    # 호가창 정보
    total_bid_volume: float
    total_ask_volume: float
    bid_ask_imbalance: float  # (bid - ask) / (bid + ask)

    # 거래량 정보
    recent_volume_1m: float   # 최근 1분 거래량
    recent_volume_5m: float   # 최근 5분 거래량
    vwap_1m: float

    # 시그널 관련
    price_momentum: float     # 가격 변화율
    volume_spike: bool        # 거래량 급증
    large_trade_detected: bool

class MarketStateManager:
    async def update_from_trade(trade: Trade)
    async def update_from_orderbook(ob: OrderBook)
    def get_current_state() -> MarketState
    def calculate_features() -> Dict[str, float]
```

#### FeatureCalculator
**역할**: 실시간 지표 계산

**계산 지표**:
- VWAP (Volume Weighted Average Price)
- Rolling Volume (1m, 5m, 15m)
- Bid-Ask Spread
- Order Book Imbalance
- Price Momentum (변화율)
- Large Trade Detection (임계값 이상)

```python
class FeatureCalculator:
    def calculate_vwap(trades: List[Trade], window: int) -> float
    def calculate_rolling_volume(trades: List[Trade], window_sec: int) -> float
    def calculate_imbalance(orderbook: OrderBook) -> float
    def calculate_momentum(prices: List[float], window: int) -> float
    def detect_large_trade(trade: Trade) -> bool
```

#### SignalEngine
**역할**: 진입/청산 시그널 생성 (기존 유지)

---

### 2.5 Monitoring & Observability

#### Metrics (Prometheus)
```python
# 데이터 수집 메트릭
data_received_total = Counter('data_received_total', ['data_type', 'symbol'])
data_processing_latency = Histogram('data_processing_latency_seconds', ['stage'])
connection_status = Gauge('websocket_connection_status', ['symbol'])

# 데이터 품질 메트릭
data_validation_errors = Counter('data_validation_errors_total', ['error_type'])
duplicate_data_count = Counter('duplicate_data_count_total', ['data_type'])
out_of_order_count = Counter('out_of_order_count_total', ['data_type'])

# 비즈니스 메트릭
signal_generated = Counter('signal_generated_total', ['signal_type'])
market_state_updates = Counter('market_state_updates_total')
```

#### Logging
```python
# 구조화된 로그
{
    "timestamp": "2025-10-23T01:30:00.123Z",
    "level": "INFO",
    "component": "websocket_connector",
    "event": "connection_established",
    "symbol": "BTCUSDT",
    "latency_ms": 45,
    "metadata": {...}
}
```

#### Alerting
- Connection down > 30초
- Data validation error rate > 1%
- Latency > 200ms
- Message buffer full

---

## 3. 데이터 흐름 (Sequence Diagram)

```
WebSocket    Parser    Validator    Normalizer    Storage    StateManager    SignalEngine
    │            │           │            │            │            │              │
    │─ Raw JSON ─▶│           │            │            │            │              │
    │            │─ Parsed ──▶│            │            │            │              │
    │            │           │─ Valid ────▶│            │            │              │
    │            │           │            │─Normalized─▶│            │              │
    │            │           │            │            │─ Update ───▶│              │
    │            │           │            │            │            │─ State ──────▶│
    │            │           │            │            │            │              │─ Signal
```

**처리 시간 목표**:
1. WebSocket → Parser: < 1ms
2. Parser → Validator: < 1ms
3. Validator → Normalizer: < 2ms
4. Normalizer → Storage: < 5ms (Hot), < 50ms (Warm)
5. Storage → StateManager: < 1ms
6. StateManager → SignalEngine: < 10ms

**Total Latency 목표**: < 50ms (WebSocket → Signal)

---

## 4. 확장성 고려사항

### 4.1 다중 페어 지원
```python
# 페어별로 독립적인 파이프라인 생성
symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

for symbol in symbols:
    pipeline = DataPipeline(symbol)
    await pipeline.start()
```

### 4.2 수평 확장 (향후)
- Kafka/Redis Streams로 데이터 분산
- 처리 로직을 별도 Worker로 분리
- Load balancing

### 4.3 장애 복구
- Circuit Breaker Pattern
- Graceful Degradation (일부 기능 비활성화)
- Checkpoint/Resume (데이터 재수집)

---

## 5. 구현 우선순위

### Phase 1: 핵심 파이프라인 (1주)
- [ ] WebSocketConnector 개선 (Auto Reconnection)
- [ ] DataValidator 구현
- [ ] DataNormalizer 구현
- [ ] HotStorage 구조 개선

### Phase 2: 상태 관리 (1주)
- [ ] MarketStateManager 구현
- [ ] FeatureCalculator 구현
- [ ] SignalEngine 개선 (상태 기반)

### Phase 3: 영속성 (1주)
- [ ] InfluxDB 연동
- [ ] Parquet 저장 로직
- [ ] 데이터 보관 정책

### Phase 4: 모니터링 (1주)
- [ ] Prometheus Metrics
- [ ] 구조화된 로깅
- [ ] Alerting 설정
- [ ] Grafana Dashboard

---

## 6. 성능 최적화 전략

### 6.1 메모리 최적화
- Ring Buffer로 메모리 상한 제한
- Object Pooling (Trade, OrderBook 재사용)
- Lazy Evaluation

### 6.2 CPU 최적화
- Asyncio 병렬 처리
- Cython으로 핫스팟 최적화
- NumPy/Pandas vectorization

### 6.3 I/O 최적화
- Batch Write (InfluxDB)
- Async File I/O
- Buffer 크기 튜닝

---

## 7. 보안 고려사항

- API Key 암호화 저장
- WebSocket over TLS
- Rate Limiting
- Input Sanitization

---

## 8. 테스트 전략

### Unit Tests
- Parser, Validator, Normalizer 단위 테스트

### Integration Tests
- WebSocket Mock 서버로 E2E 테스트

### Performance Tests
- Latency 측정
- Throughput 테스트 (msg/sec)
- Memory Leak 검사

### Chaos Engineering
- 연결 끊김 시나리오
- 잘못된 데이터 주입
- 부하 테스트

---

## 9. 운영 가이드

### 배포
```bash
docker-compose up -d
```

### 모니터링
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090

### 로그 확인
```bash
tail -f logs/trading_bot.log
```

### 백업
```bash
# InfluxDB 백업
influxd backup -portable /backup/influxdb

# Parquet 파일 백업
rsync -av data/ backup/data/
```

---

## 10. 기술 스택 요약

| Layer              | Technology          | 용도                  |
|--------------------|---------------------|----------------------|
| Data Source        | Binance WebSocket   | 실시간 시장 데이터      |
| Connection         | Python websockets   | WebSocket 클라이언트   |
| Processing         | Python asyncio      | 비동기 처리            |
| Hot Storage        | Python deque        | 인메모리 버퍼          |
| Warm Storage       | InfluxDB            | 시계열 데이터베이스     |
| Cold Storage       | Parquet + S3        | 장기 보관             |
| Monitoring         | Prometheus + Grafana| 메트릭 & 대시보드      |
| Logging            | Python logging      | 구조화된 로그          |
| Testing            | pytest + pytest-asyncio | 테스트 프레임워크  |

---

**문서 버전**: v1.0
**작성일**: 2025-10-23
**작성자**: Claude (AI Architecture Design)
