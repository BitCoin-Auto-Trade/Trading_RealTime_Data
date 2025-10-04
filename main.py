import asyncio
from data_collector.websocket_connector import WebSocketConnector
from core.signal_engine_v1 import SignalEngine
from utils.logger_utils import setup_logger


class TradingBot:
    """메인 트레이딩 봇"""
    
    def __init__(self):
        self.logger = setup_logger("main")
        self.ws = WebSocketConnector()
        self.signal_engine = SignalEngine()
        self.current_position = None  # None | "LONG" | "SHORT"
    
    async def on_message(self, data_type: str, data):
        """WebSocket 메시지 핸들러"""
        
        signal = None
        
        if data_type == "trade":
            # 체결 데이터 업데이트
            signal = self.signal_engine.update_trade(data)
        
        elif data_type == "orderbook":
            # 호가창 데이터 업데이트 및 시그널 체크
            signal = self.signal_engine.update_orderbook(data)
        
        # 시그널 발생 시 처리
        if signal and self.current_position is None:
            self.logger.info(f"✅ {signal} 진입 시그널 발생")
            # TODO: order_executor로 주문 실행
            self.current_position = signal
        
        # 포지션 있을 때 청산 체크 (간단한 예시)
        # 실제로는 market_state 객체 만들어서 전달해야 함
    
    async def start(self):
        """봇 시작"""
        self.logger.info("🚀 트레이딩 봇 시작")
        await self.ws.start(self.on_message)
    
    async def stop(self):
        """봇 종료"""
        self.logger.info("🛑 트레이딩 봇 종료")
        await self.ws.stop()


async def main():
    bot = TradingBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n사용자 중단")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())