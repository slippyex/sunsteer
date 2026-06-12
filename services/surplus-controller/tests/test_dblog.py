import src.dblog as dblog


class _Cur:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _Cur(self._row)


def test_last_switch_ages_parses_floats():
    assert dblog.last_switch_ages(_Conn((1800.0, 673.0))) == (1800.0, 673.0)


def test_last_switch_ages_none_when_no_history():
    assert dblog.last_switch_ages(_Conn((None, None))) == (None, None)


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
    c = _LConn(); assert dblog.live_conn(c, lambda: "NEW") is c

def test_live_conn_dead_reconnects():
    c = _LConn(dead=True)
    assert dblog.live_conn(c, lambda: "NEW") == "NEW" and c.closed_called

def test_live_conn_none_connects():
    assert dblog.live_conn(None, lambda: "NEW") == "NEW"


# --- write_decision includes the enriched audit columns ---

class _CapCur:
    def __init__(self): self.sql = None; self.params = None
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params): self.sql, self.params = sql, params

class _CapConn:
    def __init__(self): self.cur = _CapCur()
    def cursor(self): return self.cur

def test_write_decision_logs_audit_inputs():
    conn = _CapConn()
    dblog.write_decision(conn, "auto", 12.0, 1960.0, 5.0, False, "switched_off",
                         "state_stale_failsafe", available_w=12.0, relay_on_before=True,
                         state_age_s=47.0, shelly_reachable=True)
    sql, params = conn.cur.sql, conn.cur.params
    for col in ("available_w", "relay_on_before", "state_age_s", "shelly_reachable"):
        assert col in sql
    assert sql.count("%s") == 11        # 7 original + 4 new
    assert params == ("auto", 12.0, 1960.0, 5.0, False, "switched_off",
                      "state_stale_failsafe", 12.0, True, 47.0, True)
