"""Lightweight DE/EN i18n: flat key table + per-request language from cookie/query.

No gettext machinery — a dict is greppable, diffable and exactly as dynamic as this UI
needs. Default language comes from UI_DEFAULT_LANG (en unless overridden); users
switch per cookie or ?lang= query.
"""
import os

LANGS = ("de", "en")
DEFAULT = os.environ.get("UI_DEFAULT_LANG", "en")
if DEFAULT not in LANGS:
    DEFAULT = "en"

S = {
    # ── header / navigation ────────────────────────────────────────────────
    "app_title":        ("PV-Überschuss-Steuerung", "PV Surplus Control"),
    "subtitle":         ("PV → SG-READY LEITSTAND", "PV → SG-READY CONTROL"),
    "settings":         ("Einstellungen", "Settings"),
    "close":            ("Schließen", "Close"),
    "updated_every":    ("aktualisiert alle {s} s", "refreshes every {s} s"),
    "sec_state":        ("Zustand", "State"),
    "sec_tagesverlauf": ("Tagesverlauf", "Daily chart"),

    # ── mode control ───────────────────────────────────────────────────────
    "mode_auto":   ("Auto", "Auto"),
    "mode_manual": ("Manuell", "Manual"),
    "mode_paused": ("Pause", "Pause"),
    "on":          ("EIN", "ON"),
    "off":         ("AUS", "OFF"),

    # ── status KPIs ────────────────────────────────────────────────────────
    "kpi_surplus":      ("Überschuss", "Surplus"),
    "kpi_production":   ("Produktion", "Production"),
    "kpi_consumption":  ("Verbrauch", "Consumption"),
    "kpi_wp_power":     ("WP-Leistung", "HP power"),
    "relay":            ("Relais", "Relay"),
    "threshold":        ("Schwelle", "Threshold"),
    "self_consumption": ("Eigenverbrauch", "Self-consumption"),
    "autarky":          ("Autarkie", "Self-sufficiency"),

    # ── why card (rendered in explain.py) ──────────────────────────────────
    "why_unknown":        ("Status nicht verfügbar", "Status unavailable"),
    "why_paused":         ("Pausiert (Not-Aus)", "Paused (kill switch)"),
    "why_paused_detail":  ("Relais zwangs-aus", "relay forced off"),
    "why_manual_on":      ("WP manuell EIN", "HP manually ON"),
    "why_manual_off":     ("WP manuell AUS", "HP manually OFF"),
    "why_on":             ("WP läuft", "HP running"),
    "why_off":            ("WP aus", "HP off"),
    "why_stale":          ("Messdaten veraltet — WP sicherheitshalber aus",
                           "Measurements stale — HP off as a precaution"),
    "why_stale_detail":   ("SHM-Überschuss nicht verfügbar ({age}); Auto-Abschaltung aktiv.",
                           "SHM surplus unavailable ({age}); automatic shutdown active."),
    "why_stale_age":      ("seit {n} s", "for {n} s"),
    "why_stale_nodata":   ("keine Daten", "no data"),
    "why_surplus":        ("Überschuss {s} W", "Surplus {s} W"),
    "why_minrun_left":    ("Mindestlaufzeit noch {m} min", "min runtime: {m} min left"),
    "why_net_feedin":     ("netto +{s} W Einspeisung", "net +{s} W feed-in"),
    "why_net_draw":       ("netto {s} W Netzbezug", "net {s} W grid draw"),
    "why_available":      ("{net} · verfügbar {a} W", "{net} · available {a} W"),
    "why_available_ok":   ("{net} · verfügbar {a} W > Aus-Schwelle {o} W",
                           "{net} · available {a} W > off threshold {o} W"),
    "why_off_streak":     ("{n}/{d} Zyklen unter Aus-Schwelle ({o} W)",
                           "{n}/{d} cycles below off threshold ({o} W)"),
    "why_below":          ("Überschuss {s} W unter Schwelle {t} W",
                           "Surplus {s} W below threshold {t} W"),
    "why_on_streak":      ("{n}/{d} Zyklen über Schwelle", "{n}/{d} cycles above threshold"),
    "why_minoff_wait":    ("warte Mindestpause", "waiting out min pause"),
    "why_minoff_left":    ("noch {m} min", "{m} min left"),

    # ── ticker ─────────────────────────────────────────────────────────────
    "ticker_unknown": ("WP –", "HP –"),

    # ── balance / effectiveness ────────────────────────────────────────────
    "export":           ("Einspeisung", "Feed-in"),
    "import":           ("Bezug", "Grid import"),
    "forecast_today":   ("Solar-Prognose heute:", "Solar forecast today:"),
    "remaining":        ("Rest", "remaining"),
    "savings_label":    ("Durch Steuerung selbst genutzt:", "Self-consumed thanks to control:"),
    "estimated":        ("(geschätzt ⓘ)", "(estimated ⓘ)"),
    "total_lc":         ("gesamt", "total"),
    "wp_runtime_today": ("WP-Laufzeit heute", "HP runtime today"),

    # ── vicare card ────────────────────────────────────────────────────────
    "dhw_tank":     ("WW-Speicher", "DHW tank"),
    "buffer":       ("Puffer", "Buffer"),
    "outside":      ("Außen", "Outside"),
    "supply":       ("Vorlauf", "Flow"),
    "scop_tip":     ("Saisonale Effizienz-Kennzahlen von Viessmann (langsam, ~täglich aktualisiert). Auf der Vitocal 250-A liefern SCOP und SPF dieselbe Quelle.",
                     "Seasonal efficiency figures from Viessmann (slow, ~daily). On the Vitocal 250-A, SCOP and SPF share one source."),
    "rod_warn":     ("Heizstab lief heute: {kwh} kWh — teurer Direktstrom statt Wärmepumpe.",
                     "Backup heater ran today: {kwh} kWh — expensive resistive heating instead of the heat pump."),
    "compressor":   ("Verdichter", "Compressor"),
    "starts":       ("Starts", "Starts"),
    "runtime":      ("Laufzeit", "Runtime"),
    "thermal":      ("therm.", "thermal"),
    "el_pending_tip": ("Viessmann meldet den elektrischen Tagesverbrauch verzögert nach der erzeugten Wärme. Sobald er da ist, erscheinen el. kWh und COP.",
                       "Viessmann reports the day's electrical consumption later than the heat produced. Once it arrives, elec. kWh and COP appear."),

    # ── inverter card ──────────────────────────────────────────────────────
    "ac_power":        ("AC-Leistung", "AC power"),
    "east":            ("Ost", "East"),
    "west":            ("West", "West"),
    "device_temp":     ("Geräte-Temp.", "Device temp."),
    "insulation":      ("Isolation", "Insulation"),
    "insulation_tip":  ("DC-Isolationswiderstand — fällt er Richtung ~200 kΩ, deutet das auf einen DC-Fehler/Feuchte hin.",
                        "DC insulation resistance — dropping towards ~200 kΩ indicates a DC fault / moisture."),
    "grid_v_tip":      ("Netzspannung je Phase — dauerhaft >253 V führt zu Abregelung (stiller Ertragsverlust).",
                        "Grid voltage per phase — sustained >253 V causes derating (silent yield loss)."),
    "frequency":       ("Frequenz", "Frequency"),
    "inv_unreachable": ("Wechselrichter nicht erreichbar.", "Inverter unreachable."),
    "inv_ok":          ("Ok", "Ok"),
    "inv_warning":     ("Warnung", "Warning"),
    "inv_fault":       ("Fehler", "Fault"),
    "inv_off":         ("Aus", "Off"),
    "inv_stop":        ("Stop", "Stop"),
    "inv_code":        ("Code {c}", "Code {c}"),

    # ── decisions table ────────────────────────────────────────────────────
    "decisions_title": ("Letzte Entscheidungen", "Recent decisions"),
    "col_time":        ("Zeit", "Time"),
    "col_mode":        ("Modus", "Mode"),
    "col_action":      ("Aktion", "Action"),
    "col_reason":      ("Grund", "Reason"),
    "reason_surplus_threshold_met":       ("Überschuss über Schwelle", "surplus above threshold"),
    "reason_surplus_below_off_threshold": ("Überschuss unter Aus-Schwelle", "surplus below off threshold"),
    "reason_state_stale_failsafe":        ("Messdaten veraltet (Fail-safe)", "stale data (fail-safe)"),
    "reason_manual":                      ("manuell", "manual"),
    "reason_manual_hold":                 ("manuell gehalten", "manual hold"),
    "reason_paused":                      ("pausiert", "paused"),
    "reason_external_change":             ("extern (Watchdog/SMA)", "external (watchdog/SMA)"),
    "reason_extern (Watchdog/SMA)":       ("extern (Watchdog/SMA)", "external (watchdog/SMA)"),
    "reason_shelly_write_failed":         ("Shelly-Schreibfehler", "Shelly write failed"),
    "reason_surplus_ok":          ("Überschuss ausreichend", "surplus sufficient"),
    "reason_waiting_surplus":     ("warte auf Überschuss", "waiting for surplus"),
    "reason_waiting_min_offtime": ("warte Mindestpause", "waiting out min off-time"),
    "reason_min_runtime":         ("Mindestlaufzeit aktiv", "min runtime active"),

    # ── weather ────────────────────────────────────────────────────────────
    "weather_title":      ("Wetter", "Weather"),
    "weather_today":      ("Heute", "Today"),
    "weather_tomorrow":   ("Morgen", "Tomorrow"),
    "sun_hours":          ("h Sonne", "h sun"),
    "weather_unavail":    ("Wetterdaten gerade nicht verfügbar.", "Weather data currently unavailable."),
    "wmo_0":  ("Klar", "Clear"), "wmo_1": ("Heiter", "Mostly clear"),
    "wmo_2":  ("Teils bewölkt", "Partly cloudy"), "wmo_3": ("Bedeckt", "Overcast"),
    "wmo_45": ("Nebel", "Fog"), "wmo_48": ("Reifnebel", "Rime fog"),
    "wmo_51": ("Leichter Niesel", "Light drizzle"), "wmo_53": ("Niesel", "Drizzle"),
    "wmo_55": ("Starker Niesel", "Heavy drizzle"),
    "wmo_61": ("Leichter Regen", "Light rain"), "wmo_63": ("Regen", "Rain"),
    "wmo_65": ("Starker Regen", "Heavy rain"),
    "wmo_71": ("Leichter Schnee", "Light snow"), "wmo_73": ("Schnee", "Snow"),
    "wmo_75": ("Starker Schnee", "Heavy snow"),
    "wmo_80": ("Schauer", "Showers"), "wmo_81": ("Schauer", "Showers"),
    "wmo_82": ("Heftige Schauer", "Violent showers"),
    "wmo_95": ("Gewitter", "Thunderstorm"), "wmo_96": ("Gewitter + Hagel", "Thunderstorm + hail"),
    "wmo_99": ("Schweres Gewitter", "Severe thunderstorm"),

    # ── index sections / history ───────────────────────────────────────────
    "sec_vicare":       ("Wärmepumpe · ViCare", "Heat pump · ViCare"),
    "sec_inverter":     ("Wechselrichter · SMA", "Inverter · SMA"),
    "sec_eff":          ("Wirksamkeit", "Effectiveness"),
    "sec_history":      ("WP-Historie", "HP history"),
    "btn_7d":           ("7 Tage", "7 days"),
    "btn_30d":          ("30 Tage", "30 days"),
    "btn_90d":          ("Quartal", "Quarter"),
    "btn_365d":         ("Jahr", "Year"),
    "hist_savings":     ("Ersparnis durch SG-Ready", "Savings from SG-Ready"),
    "hist_savings_note":("· grün = WP aus PV-Überschuss · geschätzt", "· green = HP on PV surplus · estimated"),
    "hist_temps":       ("Temperaturen (°C)", "Temperatures (°C)"),
    "hist_run":         ("WP-Lauf vs. Überschuss", "HP run vs. surplus"),
    "hist_comp":        ("Verdichter (rps · Starts)", "Compressor (rps · starts)"),
    "hist_eff":         ("Effizienz", "Efficiency"),
    "hist_eff_note":    ("· geschätzt, ViCare-Lag ~1–2 T", "· estimated, ViCare lag ~1–2 d"),
    "hist_strings":     ("WR: Ost vs. West (DC-Leistung)", "Inverter: east vs. west (DC power)"),
    "hist_strings_note":("· String A / B", "· string A / B"),

    # ── chart labels (rendered into JS) ────────────────────────────────────
    "ch_surplus":   ("Überschuss (W)", "Surplus (W)"),
    "ch_threshold": ("Schwelle (W)", "Threshold (W)"),
    "ch_wp_on":     ("WP läuft", "HP running"),
    "ch_cloud":     ("Bewölkung (%)", "Cloud cover (%)"),
    "ch_temp":      ("Temperatur (°C)", "Temperature (°C)"),
    "ch_pv":        ("PV-gedeckt (kWh)", "PV-covered (kWh)"),
    "ch_grid":      ("Netz (kWh)", "Grid (kWh)"),
    "ch_saved_cum": ("∑ gespart (€)", "∑ saved (€)"),
    "ch_saved":     ("€ gespart", "€ saved"),
    "ch_dhw":       ("WW", "DHW"),
    "ch_buffer":    ("Puffer", "Buffer"),
    "ch_supply":    ("Vorlauf", "Flow"),
    "ch_outside":   ("Außen", "Outside"),
    "ch_rps":       ("Drehzahl (rps)", "Speed (rps)"),
    "ch_kwh_est":   ("kWh (gesch.)", "kWh (est.)"),
    "ch_east":      ("Ost (A)", "East (A)"),
    "ch_west":      ("West (B)", "West (B)"),

    # ── settings form ──────────────────────────────────────────────────────
    "cycles":             ("Zyklen", "cycles"),
    "f_threshold_base":   ("Basis-Schwelle", "Base threshold"),
    "h_threshold_base":   ("Überschuss-Schwelle an trüben Tagen (Basis). Ab so viel Einspeisung wird die WP angefordert.",
                           "Surplus threshold on dull days (base). The HP is requested once feed-in exceeds this."),
    "f_threshold_min":    ("Min-Schwelle", "Min threshold"),
    "h_threshold_min":    ("Untergrenze der adaptiven Schwelle — an sonnigen Tagen wird bis hierher abgesenkt.",
                           "Lower bound of the adaptive threshold — on sunny days it is lowered down to this."),
    "f_threshold_off":    ("Off-Schwelle", "Off threshold"),
    "h_threshold_off":    ("Unter diesem Überschuss wird wieder abgeschaltet (Hysterese; muss unter der Min-Schwelle liegen).",
                           "Below this surplus the HP is switched off again (hysteresis; must stay below the min threshold)."),
    "f_on_delay":         ("On-Delay", "On delay"),
    "h_on_delay":         ("So viele Loop-Zyklen (à ~15 s) muss der Überschuss am Stück über der Schwelle liegen, bevor eingeschaltet wird. Höher = träger gegen Wolken.",
                           "The surplus must stay above the threshold for this many consecutive loop cycles (~15 s each) before switching on. Higher = more inert against clouds."),
    "f_off_delay":        ("Off-Delay", "Off delay"),
    "h_off_delay":        ("So viele Zyklen muss der Überschuss unter der Off-Schwelle liegen, bevor abgeschaltet wird.",
                           "The surplus must stay below the off threshold for this many cycles before switching off."),
    "f_min_runtime":      ("Mindestlaufzeit", "Min runtime"),
    "h_min_runtime":      ("Mindestlaufzeit nach dem Einschalten — schützt den Verdichter vor Takten. Sie fährt durch, auch wenn der Überschuss kurz einbricht.",
                           "Minimum runtime after switching on — protects the compressor from short-cycling. It rides through brief surplus dips."),
    "f_min_offtime":      ("Mindestpause", "Min pause"),
    "h_min_offtime":      ("Mindestpause nach dem Ausschalten, bevor wieder eingeschaltet werden darf.",
                           "Minimum pause after switching off before the HP may start again."),
    "f_full_sun_ref":     ("Volle-Sonne-Referenz", "Full-sun reference"),
    "h_full_sun_ref":     ("Prognostizierter Resttagesertrag, ab dem als „voll sonnig“ gilt → Schwelle = Min. Höher = die WP wird seltener so aggressiv.",
                           "Forecast remaining-day yield that counts as “fully sunny” → threshold = min. Higher = the HP is rarely that aggressive."),
    "f_feed_in":          ("Einspeisung", "Feed-in tariff"),
    "h_feed_in":          ("Einspeisevergütung — nur für die €-Wirksamkeitsrechnung, beeinflusst die Steuerung nicht.",
                           "Feed-in tariff — only used for the € effectiveness figures, does not affect control."),
    "f_grid_price":       ("Bezug", "Grid price"),
    "h_grid_price":       ("Strom-Bezugspreis — nur für die €-Wirksamkeitsrechnung, beeinflusst die Steuerung nicht.",
                           "Grid electricity price — only used for the € effectiveness figures, does not affect control."),
    "f_wp_nominal":       ("WP-Nennleistung", "HP nominal power"),
    "h_wp_nominal":       ("Elektrische Leistungsaufnahme der Wärmepumpe im Betrieb. Der Shelly misst sie nicht (reiner SG-Ready-Signalkontakt), daher wird WP-Leistung & selbst genutzte kWh aus Laufzeit × diesem Wert GESCHÄTZT. Bei einem echten Zähler (z. B. Shelly EM) später ersetzbar.",
                           "Electrical draw of the heat pump while running. The Shelly doesn't meter it (pure SG-Ready signal contact), so HP power & self-consumed kWh are ESTIMATED from runtime × this value. Replaceable once a real meter (e.g. Shelly EM) exists."),
    "adaptive_threshold": ("Adaptive Schwelle", "Adaptive threshold"),
    "h_adaptive":         ("An: die Schwelle sinkt bei guter Solar-Prognose Richtung Min-Schwelle. Aus: immer die Basis-Schwelle.",
                           "On: the threshold drops towards the min threshold when the solar forecast is good. Off: always the base threshold."),
    "save":               ("Speichern", "Save"),
    "saved":              ("gespeichert", "saved"),
    "db_unreachable":     ("Datenbank nicht erreichbar — nicht gespeichert",
                           "Database unreachable — not saved"),
}

_IDX = {"de": 0, "en": 1}


def get_lang(request) -> str:
    """Language from ?lang= (wins) or cookie, validated; falls back to DEFAULT."""
    lang = request.query_params.get("lang") or request.cookies.get("lang") or DEFAULT
    return lang if lang in LANGS else DEFAULT


def t(lang: str, key: str, default: str = None, **fmt) -> str:
    pair = S.get(key)
    if pair is None:
        return default if default is not None else key
    text = pair[_IDX.get(lang, 0)]
    return text.format(**fmt) if fmt else text
