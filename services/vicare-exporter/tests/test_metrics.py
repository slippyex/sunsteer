from src import metrics


def test_set_from_handles_none_and_numbers():
    metrics.set_from({"dhw_temp_c": 52.6, "outside_temp_c": None,
                      "scop_total": 5.2, "compressor_starts": 194})
    assert metrics.GAUGES["dhw_temp_c"]._value.get() == 52.6
    assert metrics.GAUGES["scop_total"]._value.get() == 5.2


def test_string_fields_are_not_gauged():
    assert "dhw_mode" not in metrics.GAUGES
    assert "energy_read_at" not in metrics.GAUGES


def test_budget_metrics_exist():
    assert metrics.API_CALLS is not None
    assert metrics.BUDGET_EXHAUSTED is not None
    assert metrics.BUDGET_USED is not None
    assert metrics.LAST_SUCCESS is not None


def test_energy_read_at_parsed_to_epoch():
    metrics.set_from({"energy_read_at": "2026-06-05T16:37:40.815Z"})
    assert metrics.ENERGY_READ_AT._value.get() > 1.7e9   # plausible 2026 unix ts


def test_energy_read_at_garbage_ignored():
    before = metrics.ENERGY_READ_AT._value.get()
    metrics.set_from({"energy_read_at": "not-a-date"})
    assert metrics.ENERGY_READ_AT._value.get() == before
