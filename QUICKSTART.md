# 빠른 시작 가이드

## 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정 (선택사항)
# .env 파일 생성하여 API 키 입력 (실제 거래 시 필요)
echo "BINANCE_API_KEY=your_key_here" > .env
echo "BINANCE_API_SECRET=your_secret_here" >> .env
```

## 실행

```bash
# 봇 시작
python main.py
```

## 주요 기능

| 컴포넌트 | 기능 |
|----------|------|
| 데이터 검증 | 중복, NULL, 순서 체크 |
| 데이터 정규화 | VWAP, 대형 거래 감지, 호가 불균형 계산 |
| Auto Reconnection | Exponential Backoff 재연결 |
| 시장 상태 관리 | 가격 모멘텀, 거래량 급증 실시간 추적 |
| 저장소 | SortedDict 시간 인덱싱 (O(log N)) |
| 모니터링 | 구조화된 통계 및 로깅 |

## 데이터 파이프라인

### 아키텍처
```python
from core.data_pipeline import DataPipeline

# 파이프라인 생성
pipeline = DataPipeline(symbol="BTCUSDT")
await pipeline.start()
```

**처리 플로우:**
```
WebSocket → Validator → Normalizer → Storage → StateManager → Callback
```

**각 단계:**
1. **WebSocket**: 바이낸스에서 실시간 데이터 수신
2. **Validator**: 데이터 품질 검증 (중복, NULL, 순서)
3. **Normalizer**: 지표 계산 (VWAP, 대형 거래, 호가 불균형)
4. **Storage**: 고속 인메모리 저장 (시간 인덱싱)
5. **StateManager**: 시장 상태 업데이트
6. **Callback**: SignalEngine 등에 전달

### 2. 시장 상태 조회
```python
state = pipeline.get_current_state()
print(f"가격: {state.last_price}")
print(f"모멘텀: {state.price_momentum}")
print(f"불균형: {state.bid_ask_imbalance}")
```

### 3. 통계 확인
```python
# 저장소 통계
storage_stats = pipeline.get_storage_stats()

# 검증 통계
validation_stats = pipeline.get_validation_stats()

# WebSocket 통계
ws_stats = pipeline.websocket.get_stats()
```

## 커스터마이징

### 시그널 콜백 설정
```python
async def on_state_update(data_type, data, state):
    if data_type == "trade" and data.is_large_trade:
        print(f"대형거래: {data.amount_usdt:,.0f} USDT")

    # 커스텀 시그널 로직
    if state.price_momentum > 0.01:  # 1% 이상 상승
        print("강한 상승 모멘텀 감지!")

pipeline = DataPipeline(
    symbol="BTCUSDT",
    on_state_update=on_state_update
)
```

### 설정 변경
```python
# config/settings.py에서 설정 조정
from config.settings import Settings

# 트레이딩 설정
Settings.trading.min_trade_amount_usdt = 20000.0  # 대형거래 임계값
Settings.trading.price_spike_threshold = 0.002     # 0.2% 가격 변화
Settings.trading.imbalance_threshold = 0.7         # 호가 불균형

# 데이터 설정
Settings.data.hot_storage_max_trades = 20000       # 저장소 크기
Settings.data.ws_reconnect_max_attempts = 20       # 최대 재연결 시도
```

## 테스트

### 단위 테스트
```bash
pytest tests/
```

### 데이터 파이프라인 테스트
```bash
python -m core.data_pipeline
```

## 모니터링

### 로그 확인
```bash
tail -f trading_bot.log
```

### 실시간 통계 (향후 추가 예정)
```bash
# Prometheus metrics
curl http://localhost:9090/metrics

# Grafana dashboard
http://localhost:3000
```

## 문제 해결

### WebSocket 연결 실패
- 네트워크 연결 확인
- Binance API 상태 확인
- 방화벽 설정 확인

### 메모리 사용량 증가
- HotStorage TTL 조정 (기본 1시간)
- max_trades, max_orderbooks 값 감소

### 데이터 검증 에러 증가
```python
# 검증 통계 확인
stats = pipeline.get_validation_stats()
print(stats['error_counts'])  # 에러 타입별 카운트
```

## 다음 단계

1. **백테스팅**: 과거 데이터로 전략 검증
2. **페이퍼 트레이딩**: 실전 없이 시뮬레이션
3. **실전 투입**: 소액으로 실전 테스트
4. **모니터링 설정**: Prometheus + Grafana
5. **데이터 저장**: InfluxDB 연동

## 참고 문서

- [ARCHITECTURE.md](ARCHITECTURE.md): 전체 아키텍처 설계
- [README.md](README.md): 프로젝트 개요
