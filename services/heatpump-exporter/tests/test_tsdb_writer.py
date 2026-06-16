from src import tsdb_writer


class FakeCur:
    def __init__(self):
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params


class FakeConn:
    def __init__(self):
        self.cur = FakeCur()

    def cursor(self):
        return self.cur


def test_write_builds_insert_with_all_fields():
    conn = FakeConn()
    data = {k: None for k in tsdb_writer.COLUMNS}
    data["dhw_temp_c"] = 52.6
    data["compressor_starts"] = 194
    tsdb_writer.write(conn, data)
    assert "INSERT INTO heatpump_telemetry (time," in conn.cur.sql
    assert conn.cur.params[tsdb_writer.COLUMNS.index("dhw_temp_c")] == 52.6
    assert conn.cur.params[tsdb_writer.COLUMNS.index("compressor_starts")] == 194
    assert len(conn.cur.params) == len(tsdb_writer.COLUMNS)


# --- live_conn reconnect ---
class _LCur:
    def __init__(self, dead): self._dead = dead
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a):
        if self._dead: raise Exception("server closed the connection")

class _LConn:
    def __init__(self, dead=False):
        self._dead, self.closed, self.closed_called = dead, False, False
    def cursor(self): return _LCur(self._dead)
    def close(self): self.closed_called = True

def test_live_conn_healthy_returns_same():
    c = _LConn(); assert tsdb_writer.live_conn(c, lambda: "NEW") is c

def test_live_conn_dead_reconnects():
    c = _LConn(dead=True)
    assert tsdb_writer.live_conn(c, lambda: "NEW") == "NEW" and c.closed_called

def test_live_conn_none_connects():
    assert tsdb_writer.live_conn(None, lambda: "NEW") == "NEW"
