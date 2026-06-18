from src import state


def test_num_coerces():
    assert state.num("5") == 5.0
    assert state.num(3) == 3.0
    assert state.num(None) is None
    assert state.num("x") is None


def test_normalize_fresh():
    ns = state.normalize_state(
        {"surplus_w": 1500, "shm_age_s": 1.0, "shelly_reachable": True, "shelly_on": False}, 30)
    assert ns.surplus_raw == 1500.0 and ns.age == 1.0
    assert ns.state_fresh is True and ns.surplus == 1500.0
    assert ns.shelly_reachable is True and ns.shelly_on is False


def test_normalize_blind_when_none():
    ns = state.normalize_state(None, 30)
    assert ns.surplus_raw is None and ns.age is None
    assert ns.state_fresh is False and ns.surplus == 0.0


def test_normalize_stale_when_too_old():
    ns = state.normalize_state({"surplus_w": 1500, "shm_age_s": 99}, 30)
    assert ns.state_fresh is False          # age 99 > stale 30


def test_normalize_nonnumeric_surplus_is_blind():
    ns = state.normalize_state({"surplus_w": "oops", "shm_age_s": 1.0}, 30)
    assert ns.surplus_raw is None and ns.state_fresh is False and ns.surplus == 0.0
