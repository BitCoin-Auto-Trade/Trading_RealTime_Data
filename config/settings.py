import os
import dotenv

dotenv.load_dotenv()

class Settings:
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

    # 체결 폭증
    VOLUME_SPIKE_WINDOW = 2.0        # 최근 2초
    VOLUME_SPIKE_BASELINE = 10800.0  # 과거 3시간
    VOLUME_SPIKE_RATIO = 5.0         # 5배 이상
    MIN_TRADE_AMOUNT = 10000.0       # 1만 USDT 이상만 카운트
    
    # 가격 급변
    PRICE_CHANGE_WINDOW = 2.0        # 2초 내
    PRICE_CHANGE_THRESHOLD = 0.003   # 0.3% 이상 (BTC 62000 기준 186달러)
    
    # 호가 방향 일치 (보조)
    IMBALANCE_THRESHOLD = 0.65       # 65:35 이상