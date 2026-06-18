from src import reporting


def _inp(**over):
    base = dict(mode="auto", relay_on=True, eff=2000.0, fc=5.0, sun_elev=30.0, base_load=500.0,
               basis="production", avail=1500.0, surplus=1200.0, state_fresh=True, age=1.0,
               reason="surplus_ok", sun_up=True, action="no_change", on_streak=1, off_streak=0,
               on_delay_cycles=3, off_delay_cycles=3, min_runtime_s=1800, min_offtime_s=900,
               secs_since_on=100, secs_since_off=9999, wp_nominal_power_w=2000.0, loop_seconds=15)
    base.update(over)
    return reporting.ReportInputs(**base)


def test_write_sets_status(monkeypatch):
    seen = {}
    monkeypatch.setattr(reporting.status_server, "set_status", lambda **kw: seen.update(kw))
    reporting.write(_inp(), lambda now_local: (1.0, 2.0), object())
    assert seen["mode"] == "auto" and seen["available_w"] == 1500.0


def test_write_swallows_sun_window_error_into_reporting_label(monkeypatch):
    monkeypatch.setattr(reporting.status_server, "set_status", lambda **kw: None)
    hits = []
    real_labels = reporting.metrics.LOOP_ERRORS.labels
    monkeypatch.setattr(reporting.metrics.LOOP_ERRORS, "labels",
                        lambda name: hits.append(name) or real_labels(name))
    def boom(now_local):
        raise RuntimeError("sun window down")
    reporting.write(_inp(), boom, object())     # must not raise
    assert "reporting" in hits
