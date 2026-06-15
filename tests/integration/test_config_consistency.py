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


def _ddl_columns():
    """Column names declared for control_config in db/init.sql (CREATE TABLE body
    plus any ALTER TABLE ... ADD COLUMN)."""
    with open(os.path.join(ROOT, "db", "init.sql")) as f:
        sql = f.read()
    body = re.search(
        r"CREATE TABLE IF NOT EXISTS control_config\s*\((.*?)\n\);", sql, re.S
    ).group(1)
    cols = set()
    for line in body.splitlines():
        line = line.strip()
        m = re.match(r"([a-z_][a-z0-9_]*)\s+(SMALLINT|BOOLEAN|TEXT|INT|DOUBLE|TIMESTAMPTZ)", line, re.I)
        if m and m.group(1).upper() not in ("CHECK",):
            cols.add(m.group(1))
    for m in re.finditer(r"ALTER TABLE control_config ADD COLUMN IF NOT EXISTS (\w+)", sql):
        cols.add(m.group(1))
    return cols


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
