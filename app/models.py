from dataclasses import asdict, dataclass, field
from typing import Any
@dataclass(frozen=True)
class Candle:
    time_ms:int; open:float; high:float; low:float; close:float; quote_volume:float=0.; base_volume:float=0.
    def valid(self)->bool:
        v=(self.open,self.high,self.low,self.close,self.quote_volume,self.base_volume)
        return all(x==x and abs(x)!=float("inf") for x in v) and min(self.open,self.high,self.low,self.close)>0 and self.high>=max(self.open,self.close,self.low) and self.low<=min(self.open,self.close,self.high) and self.quote_volume>=0 and self.base_volume>=0
@dataclass
class Signal:
    symbol:str; market:str; side:str; status:str; score:int; entry:float|None; stop_loss:float|None
    take_profit_1:float|None; take_profit_2:float|None; net_rr:float|None; reasons:list[str]; risks:list[str]; created_at_ms:int; timeframe:str="1h"
    risk_plan:dict[str,Any]=field(default_factory=dict)
    def to_dict(self)->dict[str,Any]: return asdict(self)
