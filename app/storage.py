import json,os,sqlite3
from app.models import Signal
class SignalStore:
    def __init__(self,path:str):
        self.path=path
        if os.path.dirname(path): os.makedirs(os.path.dirname(path),exist_ok=True)
        with self._db() as d: d.execute("CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,market TEXT,side TEXT,status TEXT,score INTEGER,created_at_ms INTEGER,payload TEXT)")
    def _db(self):
        d=sqlite3.connect(self.path); d.row_factory=sqlite3.Row; return d
    def save(self,s:Signal)->int:
        with self._db() as d:
            c=d.execute("INSERT INTO signals(symbol,market,side,status,score,created_at_ms,payload) VALUES(?,?,?,?,?,?,?)",(s.symbol,s.market,s.side,s.status,s.score,s.created_at_ms,json.dumps(s.to_dict())))
            return int(c.lastrowid)
    def get(self,signal_id:int)->dict|None:
        with self._db() as d: row=d.execute("SELECT id,payload FROM signals WHERE id=?",(signal_id,)).fetchone()
        return None if row is None else {"id":row["id"],**json.loads(row["payload"])}
    def check(self)->bool:
        with self._db() as d: d.execute("SELECT 1").fetchone()
        return True
    def latest(self,n:int=50)->list[dict]:
        with self._db() as d: rows=d.execute("SELECT id,payload FROM signals ORDER BY id DESC LIMIT ?",(min(max(n,1),200),)).fetchall()
        return [{"id":r["id"],**json.loads(r["payload"])} for r in rows]
