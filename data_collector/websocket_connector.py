import asyncio
import json
import time
import websockets
from typing import Callable

from utils.logger_utils import setup_logger
from data_collector.data_parser import DataParser


class WebSocketConnector:
    """바이낸스 선물 WebSocket 연결 관리"""
    
    def __init__(self):
        self.url = "wss://fstream.binance.com/stream?streams=btcusdt@depth/btcusdt@aggTrade"
        self.logger = setup_logger("websocket")
        self.websocket = None
        self.running = False
        self.start_time = 0
        self.parser = DataParser()
        
        # 통계용
        self.trade_count = 0
        self.orderbook_count = 0
    
    async def _connect(self):
        """연결"""
        try:
            self.websocket = await websockets.connect(self.url)
            self.start_time = time.time()
            self.logger.info(f"연결 성공: {self.url}")
            return True
        except Exception as e:
            self.logger.error(f"연결 실패: {e}")
            return False
    
    async def start(self, on_message: Callable):
        """메시지 수신 시작"""
        if not await self._connect():
            return
        
        self.running = True
        
        try:
            while self.running:
                if (time.time() - self.start_time) / 3600 >= 23.5:
                    self.logger.info("24시간 제한 재연결")
                    await self.websocket.close()
                    if not await self._connect():
                        break
                
                try:
                    message = await self.websocket.recv()
                    data = json.loads(message)
                    
                    if "stream" in data and "data" in data:
                        stream_name = data["stream"]
                        raw_data = data["data"]
                        
                        # 스트림별로 파싱하여 전달
                        if "@depth" in stream_name:
                            parsed = self.parser.parse_order_book(raw_data)
                            self.orderbook_count += 1
                            
                            # 호가창 로깅 (상위 3개만)
                            bid_info = [(float(b[0]), float(b[1])) for b in parsed.bids[:3]]
                            ask_info = [(float(a[0]), float(a[1])) for a in parsed.asks[:3]]
                            
                            self.logger.info(f"[ORDERBOOK #{self.orderbook_count}] "
                                           f"매수 상위3: {bid_info} | "
                                           f"매도 상위3: {ask_info}")
                            
                            await on_message("orderbook", parsed)
                            
                        elif "@aggTrade" in stream_name:
                            parsed = self.parser.parse_trade(raw_data)
                            self.trade_count += 1
                            
                            # 체결 로깅
                            price = float(parsed.price)
                            quantity = float(parsed.quantity)
                            amount_usdt = price * quantity
                            side = "매도" if parsed.is_buyer_maker else "매수"
                            
                            self.logger.info(f"[TRADE #{self.trade_count}] "
                                           f"{side} | "
                                           f"가격: {price:,.2f} | "
                                           f"수량: {quantity:.4f} | "
                                           f"거래대금: {amount_usdt:,.0f} USDT")
                            
                            await on_message("trade", parsed)
                        
                except websockets.exceptions.ConnectionClosed:
                    self.logger.warning("연결 끊김")
                    await asyncio.sleep(5)
                    if not await self._connect():
                        break
                        
        except Exception as e:
            self.logger.error(f"오류: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """연결 종료"""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            self.logger.info(f"연결 종료 | 총 체결: {self.trade_count}개 | 총 호가창: {self.orderbook_count}개")