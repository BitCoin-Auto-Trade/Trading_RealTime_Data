# 빠른 시작 가이드

## 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정
cp .env.example .env
# .env 파일 편집하여 API 키 입력
```

## 실행

### 1. 기존 버전 (V1)
```bash
python main.py
```

### 2. 새로운 아키텍처 (V2 - 권장)
```bash
python main_v2.py
```

## V1 vs V2 차이점

| 기능 | V1 | V2 |
|------|----|----|
| 데이터 검증 | ❌ | ✅ |
| 데이터 정규화 | ❌ | ✅ |
| Auto Reconnection | 기본 | 개선 (Exponential Backoff) |
| 시장 상태 관리 | 간단 | 체계적 |
| 저장소 | deque만 | Hot Storage (인덱싱) |
| 모니터링 | 기본 로깅 | 구조화된 통계 |

## 새로운 아키텍처 주요 기능

### 1. 데이터 파이프라인
```python
from core.data_pipeline import DataPipeline

pipeline = DataPipeline(symbol="BTCUSDT")
await pipeline.start()
```

**플로우:**
```
WebSocket → Validator → Normalizer → Storage → StateManager
```

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
# config/settings.py 수정
MIN_TRADE_AMOUNT = 20000.0        # 대형거래 임계값
PRICE_SPIKE_THRESHOLD = 0.002     # 가격 급변 임계값 (0.2%)
IMBALANCE_THRESHOLD = 0.7         # 호가 불균형 임계값
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
