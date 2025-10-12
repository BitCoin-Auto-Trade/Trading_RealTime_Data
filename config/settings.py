import os
import dotenv

dotenv.load_dotenv()

class Settings:
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

    # 가격 급변 감지
    MIN_TRADE_AMOUNT = 10000.0        # 1만 USDT 이상만 저장
    PRICE_SPIKE_WINDOW = 5.0          # 5초
    PRICE_SPIKE_THRESHOLD = 0.001     # 0.1% (62000 기준 62달러)
    
    # 호가 방향 확인
    IMBALANCE_THRESHOLD = 0.65        # 65:35