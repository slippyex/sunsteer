from fastapi.testclient import TestClient
import src.app as appmod


def test_static_css_served():
    r = TestClient(appmod.app).get("/static/sunsteer.css")
    assert r.status_code == 200 and "--cyan" in r.text


def test_vendor_assets_served():
    c = TestClient(appmod.app)
    for f in ("vendor/htmx.min.js", "vendor/chart.umd.min.js",
              "vendor/chartjs-adapter-date-fns.bundle.min.js"):
        assert c.get(f"/static/{f}").status_code == 200


def test_index_has_no_cdn_references():
    import pathlib
    html = pathlib.Path("templates/index.html").read_text()
    for s in ("cdn.tailwindcss.com", "unpkg.com", "cdn.jsdelivr.net", "fonts.googleapis.com"):
        assert s not in html
