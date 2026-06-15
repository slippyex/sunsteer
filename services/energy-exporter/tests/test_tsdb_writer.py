from src.tsdb_writer import aggregate_samples


def test_aggregate_averages_power_and_takes_last_counters():
    samples = [
        {"import_w": 100, "export_w": 0, "surplus_w": -100, "l1_w": -100, "l2_w": 0, "l3_w": 0,
         "import_kwh_total": 1.0, "export_kwh_total": 2.0},
        {"import_w": 300, "export_w": 0, "surplus_w": -300, "l1_w": -300, "l2_w": 0, "l3_w": 0,
         "import_kwh_total": 1.1, "export_kwh_total": 2.0},
    ]
    a = aggregate_samples(samples)
    assert a["import_w"] == 200            # mean
    assert a["surplus_w"] == -200
    assert a["import_kwh_total"] == 1.1    # last (monotonic counter)
    assert a["export_kwh_total"] == 2.0

def test_aggregate_empty_returns_none():
    assert aggregate_samples([]) is None


# --- live_conn reconnect ---
from src import tsdb_writer as _tw


class _Cur:
    def __init__(self, dead): self._dead = dead
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a):
        if self._dead:
            raise Exception("server closed the connection")


class _Conn:
    def __init__(self, dead=False, closed=False):
        self._dead, self.closed, self.closed_called = dead, closed, False
    def cursor(self): return _Cur(self._dead)
    def close(self): self.closed_called = True


def test_live_conn_healthy_returns_same():
    c = _Conn()
    assert _tw.live_conn(c, lambda: "NEW") is c

def test_live_conn_dead_reconnects_and_closes_old():
    c = _Conn(dead=True)
    assert _tw.live_conn(c, lambda: "NEW") == "NEW"
    assert c.closed_called is True

def test_live_conn_none_connects():
    assert _tw.live_conn(None, lambda: "NEW") == "NEW"
