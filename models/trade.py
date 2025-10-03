from dataclasses import dataclass

@dataclass
class Trade:
    event_type: str       # e: "aggTrade"
    event_time: int       # E: 이벤트 시간
    symbol: str           # s: "BTCUSDT"
    aggregate_trade_id: int  # a: 집계 거래 ID
    price: str            # p: 체결 가격
    quantity: str         # q: 체결 수량
    first_trade_id: int   # f: 첫 거래 ID
    last_trade_id: int    # l: 마지막 거래 ID
    trade_time: int       # T: 거래 시간
    is_buyer_maker: bool  # m: 매수자가 메이커인지