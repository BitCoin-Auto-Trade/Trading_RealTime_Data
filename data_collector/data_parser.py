from models.order_book import OrderBook
from models.trade import Trade


class DataParser:
    """바이낸스 WebSocket 데이터를 파싱"""
    
    @staticmethod
    def parse_order_book(raw_data: dict) -> OrderBook:
        """호가창 WebSocket 데이터를 OrderBook으로 변환"""
        return OrderBook(
            event_type=raw_data.get('e'),
            event_time=raw_data.get('E'),
            symbol=raw_data.get('s'),
            first_update_id=raw_data.get('U'),
            final_update_id=raw_data.get('u'),
            bids=raw_data.get('b'),
            asks=raw_data.get('a')
        )
    
    @staticmethod
    def parse_trade(raw_data: dict) -> Trade:
        """체결 WebSocket 데이터를 Trade로 변환"""
        return Trade(
            event_type=raw_data.get('e'),
            event_time=raw_data.get('E'),
            symbol=raw_data.get('s'),
            aggregate_trade_id=raw_data.get('a'),
            price=raw_data.get('p'),
            quantity=raw_data.get('q'),
            first_trade_id=raw_data.get('f'),
            last_trade_id=raw_data.get('l'),
            trade_time=raw_data.get('T'),
            is_buyer_maker=raw_data.get('m')
        )