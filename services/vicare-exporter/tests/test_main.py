from src import main, metrics


class Budget:
    def __init__(self, allowed):
        self.allowed = allowed
        self.records = 0

    def allow(self, now):
        return self.allowed

    def record(self, now):
        self.records += 1

    def count(self, now):
        return self.records


def test_cycle_skips_when_budget_exhausted(monkeypatch):
    calls = {"poll": 0}
    monkeypatch.setattr(main.vicare_client, "poll",
                        lambda d: calls.__setitem__("poll", calls["poll"] + 1) or {"data": []})
    main.run_cycle(device=object(), conn=None, budget=Budget(allowed=False), now=0)
    assert calls["poll"] == 0
    assert metrics.BUDGET_EXHAUSTED._value.get() == 1


def test_cycle_polls_extracts_writes_records(monkeypatch):
    monkeypatch.setattr(main.vicare_client, "poll", lambda d: {"data": [
        {"feature": "heating.sensors.temperature.outside", "properties": {"value": {"value": 9.0}}}]})
    writes = {"n": 0}
    monkeypatch.setattr(main.tsdb_writer, "write", lambda c, d: writes.__setitem__("n", writes["n"] + 1))
    budget = Budget(allowed=True)
    main.run_cycle(device=object(), conn=object(), budget=budget, now=0)
    assert writes["n"] == 1
    assert budget.records == 1
    assert metrics.BUDGET_EXHAUSTED._value.get() == 0
    assert metrics.GAUGES["outside_temp_c"]._value.get() == 9.0
