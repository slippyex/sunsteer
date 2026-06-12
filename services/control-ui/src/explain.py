"""Pure presentation helpers: controller status -> localized text + progress; € effectiveness."""
import math

from .i18n import t as _t


def effectiveness_eur(kwh, grid_price, feed_in):
    """Value of self-consumed kWh: avoided grid price minus lost feed-in."""
    return round((kwh or 0) * (grid_price - feed_in), 2)


def _min_left(total_s, elapsed_s):
    return max(0, math.ceil((total_s - elapsed_s) / 60.0))


def energy_today(e_total, th_heating, th_dhw):
    """ViCare daily energy view. Viessmann's cloud posts the THERMAL day-counter before the
    ELECTRICAL one, so a period can show thermal > 0 while electrical is still 0 (lagging) —
    which would render an impossible 0 kWh-in / N kWh-out pair (and an infinite COP).
    Flag that case (`el_pending`) instead, and only compute COP once both sides are real.
    Returns {th_total, el_pending, cop_today}."""
    th = (th_heating or 0) + (th_dhw or 0)
    th_total = round(th, 1) if (th_heating is not None or th_dhw is not None) else None
    el_real = bool(e_total and e_total > 0)
    el_pending = (th_total or 0) > 0 and not el_real
    cop_today = round(th / e_total, 1) if (el_real and th > 0) else None
    return {"th_total": th_total, "el_pending": el_pending, "cop_today": cop_today}


def explain(status, cfg, lang="de"):
    """status: controller /status dict (or None). Returns
    {state, headline, detail, bar_label, bar_pct} in the requested language (default de)."""
    def t(key, **fmt):
        return _t(lang, key, **fmt)

    if not status:
        return {"state": "unknown", "headline": t("why_unknown"),
                "detail": "", "bar_label": "", "bar_pct": 0}
    mode = status.get("mode")
    relay = bool(status.get("relay_on"))
    s = round(status.get("surplus_w") or 0)
    thr = round(status.get("effective_threshold_w") or 0)
    reason = status.get("reason", "")

    if mode == "paused":
        return {"state": "paused", "headline": t("why_paused"),
                "detail": t("why_paused_detail"), "bar_label": "", "bar_pct": 0}
    if mode == "manual":
        return {"state": "manual",
                "headline": t("why_manual_on") if relay else t("why_manual_off"),
                "detail": "", "bar_label": "", "bar_pct": 0}

    # AUTO + blind: the controller can't see the surplus, so it fails the WP safe-off.
    # Surface it plainly instead of a misleading "surplus X W below threshold".
    if status.get("state_fresh") is False:
        age = status.get("state_age_s")
        age_txt = t("why_stale_age", n=round(age)) if age is not None else t("why_stale_nodata")
        return {"state": "stale", "headline": t("why_stale"),
                "detail": t("why_stale_detail", age=age_txt),
                "bar_label": "", "bar_pct": 0}

    if relay:
        if reason == "min_runtime":
            total, elapsed = status.get("min_runtime_s", 0), status.get("secs_since_on", 0)
            return {"state": "on", "headline": t("why_on"),
                    "detail": t("why_surplus", s=s),
                    "bar_label": t("why_minrun_left", m=_min_left(total, elapsed)),
                    "bar_pct": min(1.0, elapsed / total) if total else 0}
        # Running: the controller decides on the LOAD-COMPENSATED surplus (surplus + estimated
        # WP draw) vs the OFF-threshold — show that, not raw-vs-on-threshold, so the card matches
        # the actual decision. `s` is the (smoothed) raw surplus = net grid feed-in/-draw.
        avail = round(s + (cfg.get("wp_nominal_power_w") or 0))
        off_thr = round(cfg.get("threshold_off_w") or 0)
        net = t("why_net_feedin", s=s) if s >= 0 else t("why_net_draw", s=s)
        off_streak, off_delay = status.get("off_streak", 0), status.get("off_delay_cycles", 1)
        if off_streak > 0:  # surplus thinning out -> approaching switch-off
            return {"state": "on", "headline": t("why_on"),
                    "detail": t("why_available", net=net, a=avail),
                    "bar_label": t("why_off_streak", n=off_streak, d=off_delay, o=off_thr),
                    "bar_pct": min(1.0, off_streak / off_delay) if off_delay else 0}
        return {"state": "on", "headline": t("why_on"),
                "detail": t("why_available_ok", net=net, a=avail, o=off_thr),
                "bar_label": "", "bar_pct": 0}
    else:
        if reason == "waiting_min_offtime":
            total, elapsed = status.get("min_offtime_s", 0), status.get("secs_since_off", 0)
            return {"state": "off", "headline": t("why_off"),
                    "detail": t("why_minoff_wait"),
                    "bar_label": t("why_minoff_left", m=_min_left(total, elapsed)),
                    "bar_pct": min(1.0, elapsed / total) if total else 0}
        on_streak, on_delay = status.get("on_streak", 0), status.get("on_delay_cycles", 1)
        return {"state": "off", "headline": t("why_off"),
                "detail": t("why_below", s=s, t=thr),
                "bar_label": t("why_on_streak", n=on_streak, d=on_delay),
                "bar_pct": min(1.0, on_streak / on_delay) if on_delay else 0}
