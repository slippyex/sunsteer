"""Guard against config-column drift across the three places a control_config
column is declared: the controller's DEFAULTS (config.py), the UI's read/write
column list (_CONFIG_COLS in sources.py), and the DDL (db/init.sql).

These live in separate services that never import each other, so nothing else
catches a column added to one but forgotten in another. Parsed statically (ast +
regex) rather than imported — both services ship a top-level `src` package and
importing both would collide, and we only need the literals.

No DB needed; runs anywhere pytest does.
"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# pv_performance_ratio is self-calibrated by the controller, never user-settable,
# so the UI's _CONFIG_COLS deliberately omits it. Everything else must line up.
CONTROLLER_ONLY = {"pv_performance_ratio"}


def _literal_assign(path, name):
    """Return the literal value assigned to `name` at module top level."""
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def _ddl_columns_for(table):
    """Column names declared for `table` in db/init.sql (CREATE TABLE body plus any
    ALTER TABLE ... ADD COLUMN)."""
    with open(os.path.join(ROOT, "db", "init.sql")) as f:
        sql = f.read()
    body = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);", sql, re.S
    ).group(1)
    cols = set()
    for line in body.splitlines():
        line = line.strip()
        m = re.match(r"([a-z_][a-z0-9_]*)\s+(SMALLINT|BOOLEAN|TEXT|INT|DOUBLE|TIMESTAMPTZ)", line, re.I)
        if m and m.group(1).upper() not in ("CHECK",):
            cols.add(m.group(1))
    for m in re.finditer(rf"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS (\w+)", sql):
        cols.add(m.group(1))
    return cols


def _ddl_columns():
    return _ddl_columns_for("control_config")


def _dict_keys(path, name):
    """Top-level dict literal's keys (only the keys are evaluated, so non-literal values
    like tuples-of-lambdas don't matter)."""
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ) and isinstance(node.value, ast.Dict):
            return {ast.literal_eval(k) for k in node.value.keys}
    raise AssertionError(f"dict {name} not found in {path}")


def _func_source(path, name):
    """Exact source text of a top-level function `name` in `path`."""
    with open(path) as f:
        src = f.read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    raise AssertionError(f"function {name} not found in {path}")


def test_defaults_subset_of_ddl():
    defaults = set(_literal_assign(
        os.path.join(ROOT, "services", "surplus-controller", "src", "config.py"), "DEFAULTS"))
    ddl = _ddl_columns()
    missing = defaults - ddl
    assert not missing, f"DEFAULTS keys absent from control_config DDL: {missing}"


def test_ui_cols_subset_of_defaults():
    ui_cols = set(_literal_assign(
        os.path.join(ROOT, "services", "control-ui", "src", "sources.py"), "_CONFIG_COLS"))
    defaults = set(_literal_assign(
        os.path.join(ROOT, "services", "surplus-controller", "src", "config.py"), "DEFAULTS"))
    extra = ui_cols - defaults
    assert not extra, f"_CONFIG_COLS has columns the controller doesn't know: {extra}"


def test_ui_cols_are_defaults_minus_controller_only():
    ui_cols = set(_literal_assign(
        os.path.join(ROOT, "services", "control-ui", "src", "sources.py"), "_CONFIG_COLS"))
    defaults = set(_literal_assign(
        os.path.join(ROOT, "services", "surplus-controller", "src", "config.py"), "DEFAULTS"))
    assert ui_cols == defaults - CONTROLLER_ONLY, (
        "UI columns must mirror DEFAULTS minus controller-only columns "
        f"({CONTROLLER_ONLY}); diff: "
        f"missing={defaults - CONTROLLER_ONLY - ui_cols}, extra={ui_cols - defaults}"
    )


# vicare: the heatpump_vicare writer names columns from extract._FIELDS, so the field NAMES
# (not order) must match the DDL. Guard it like the control_config columns above.
def test_vicare_fields_match_heatpump_vicare_ddl():
    fields = _dict_keys(
        os.path.join(ROOT, "services", "vicare-exporter", "src", "extract.py"), "_FIELDS")
    ddl = _ddl_columns_for("heatpump_vicare") - {"time"}   # time is stamped by now()
    assert fields == ddl, (
        "vicare extract._FIELDS must match the heatpump_vicare DDL column names; diff: "
        f"missing_in_ddl={fields - ddl}, extra_in_ddl={ddl - fields}")


# The DB resilience primitives (connect + live_conn) are deliberately duplicated across the
# three services (separate images, no shared import). This guards against the copies DRIFTING:
# they are load-bearing reconnect logic and must stay identical so a fix reaches all three.
_DB_MODULES = [
    ("surplus-controller", "dblog.py"),
    ("energy-exporter", "tsdb_writer.py"),
    ("vicare-exporter", "tsdb_writer.py"),
]


def _db_func_sources(func):
    return {svc: _func_source(os.path.join(ROOT, "services", svc, "src", mod), func)
            for svc, mod in _DB_MODULES}


def test_connect_is_identical_across_services():
    srcs = _db_func_sources("connect")
    distinct = set(srcs.values())
    assert len(distinct) == 1, f"connect() has drifted across services: { {k: len(v) for k,v in srcs.items()} }"


def test_live_conn_is_identical_across_services():
    srcs = _db_func_sources("live_conn")
    distinct = set(srcs.values())
    assert len(distinct) == 1, f"live_conn() has drifted across services: { {k: len(v) for k,v in srcs.items()} }"
