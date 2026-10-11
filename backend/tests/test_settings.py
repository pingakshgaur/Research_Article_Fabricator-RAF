"""RAF settings: appearance, defaults for new articles, and the admin lock."""
import json
import re

import pytest

from app import app_settings
from conftest import ROOT

CODE = "test-" + "passcode"       # a throw-away value for these tests only


@pytest.fixture(autouse=True)
def clean_settings():
    """Every test starts and ends without a settings file, lock, session or failed-attempt count."""
    def wipe():
        app_settings.PATH.unlink(missing_ok=True)
        app_settings._tokens.clear()
        app_settings._fails.update(count=0, until=0.0)
    wipe()
    yield
    wipe()


def test_defaults_and_saving(client):
    out = client.get("/api/settings/app").json()
    assert out["settings"]["palette"] == "violet" and out["settings"]["effects"] is True and out["locked"] is False and out["unlocked"] is True
    assert [p["key"] for p in out["palettes"]] == ["violet", "rosewood", "aurora", "solar", "ember", "custom"] and out["info"]["version"]
    saved = client.put("/api/settings/app", json={"palette": "aurora", "effects": False, "workspace": "  Urban   Safety Lab ",
                                                   "article": {"authors": "Jane Doe,  John Smith ,", "target_words": 7777, "citation_style": "IEEE"},
                                                   "run": {"depth": "quick", "agents": 2}, "unknown": 1}).json()["settings"]
    assert saved["palette"] == "aurora" and saved["effects"] is False and saved["workspace"] == "Urban Safety Lab" and "unknown" not in saved
    assert saved["article"]["authors"] == ["Jane Doe", "John Smith"] and saved["article"]["target_words"] == 7500
    assert saved["article"]["article_type"] == "Empirical research article"            # untouched keys keep their value
    assert saved["run"] == {**app_settings.DEFAULTS["run"], "depth": "quick", "agents": 2}
    assert client.put("/api/settings/app", json={"palette": "custom", "custom_color": "#FF8800"}).json()["settings"]["custom_color"] == "#ff8800"
    client.put("/api/settings/app", json={"palette": "aurora"})
    for bad in ({"palette": "neon"}, {"custom_color": "orange"}, {"custom_color": "#12345"}, {"run": {"agents": 9}}, {"run": {"depth": "epic"}}, {"article": {"citation_style": "MLA"}}, {"tone": {"name": "angry"}}):
        assert client.put("/api/settings/app", json=bad).status_code == 422, bad
    assert client.get("/api/settings/app").json()["settings"]["palette"] == "aurora"      # a rejected change saves nothing
    assert client.delete("/api/settings/app").json()["settings"] == app_settings.get() == json.loads(json.dumps(app_settings.DEFAULTS))


def test_new_articles_start_from_the_defaults(client):
    client.put("/api/settings/app", json={"run": {"depth": "quick", "agents": 3, "hallucination_filter": False, "web_research": False},
                                          "tone": {"name": "analytical", "intensity": 80}})
    p = client.post("/api/projects", json={"title": "A project made after the change"}).json()
    assert p["options"]["depth"] == "quick" and p["options"]["agents"] == 3 and p["options"]["hallucination_filter"] is False
    assert p["options"]["web_research"] is False and p["options"]["style_pass"] is True and p["tone"] == {"name": "analytical", "intensity": 80}


def test_admin_lock(client):
    assert client.put("/api/settings/admin/passcode", json={"passcode": "abc"}).status_code == 422          # too short
    token = client.put("/api/settings/admin/passcode", json={"passcode": CODE}).json()["token"]
    stored = app_settings.PATH.read_text(encoding="utf-8")
    assert CODE not in stored and "hash" in stored                                                          # never stored in clear

    state = client.get("/api/settings/app").json()
    assert state["locked"] is True and state["unlocked"] is False and "admin" not in state["settings"]       # readable, nothing secret
    for method, path, body in (("put", "/api/settings/app", {"palette": "ember"}), ("delete", "/api/settings/app", None),
                               ("put", "/api/settings/llm", {"temperature": 0.5}), ("delete", "/api/settings/llm", None),
                               ("put", "/api/settings/admin/passcode", {"passcode": ""})):
        r = client.request(method, path, json=body)
        assert r.status_code == 401 and "locked" in r.json()["detail"], path
    assert client.put("/api/settings/app", json={"palette": "ember"}, headers={"X-RAF-Admin": "made-up"}).status_code == 401
    assert app_settings.get()["palette"] == "violet"

    admin = {"X-RAF-Admin": token}
    assert client.get("/api/settings/app", headers=admin).json()["unlocked"] is True
    assert client.put("/api/settings/app", json={"palette": "ember"}, headers=admin).json()["settings"]["palette"] == "ember"
    assert client.post("/api/projects", json={"title": "Articles are not behind the lock"}).status_code == 200

    assert client.post("/api/settings/admin/unlock", json={"passcode": "wrong-one"}).status_code == 401
    fresh = client.post("/api/settings/admin/unlock", json={"passcode": CODE}).json()["token"]
    client.post("/api/settings/admin/lock", headers={"X-RAF-Admin": fresh})
    assert client.put("/api/settings/app", json={"palette": "solar"}, headers={"X-RAF-Admin": fresh}).status_code == 401   # locked again

    assert client.delete("/api/settings/app", headers=admin).status_code == 200 and app_settings.locked()   # a reset keeps the lock
    assert client.put("/api/settings/admin/passcode", json={"passcode": ""}, headers=admin).json() == {"locked": False, "token": ""}
    assert client.put("/api/settings/app", json={"palette": "solar"}).status_code == 200                    # lock removed: open again


def test_repeated_wrong_passcodes_are_slowed_down(client):
    client.put("/api/settings/admin/passcode", json={"passcode": CODE})
    codes = [client.post("/api/settings/admin/unlock", json={"passcode": f"guess-{i}"}).status_code for i in range(app_settings.MAX_FAILS + 1)]
    assert codes == [401] * app_settings.MAX_FAILS + [429]
    assert client.post("/api/settings/admin/unlock", json={"passcode": CODE}).status_code == 429             # even the right one has to wait


def test_custom_theme_is_readable_for_any_colour():
    """Runs the theme engine (frontend/src/customTheme.js) over the whole colour space with Node and checks every text pair."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    out = subprocess.run([node, str(ROOT / "backend/tests/custom_theme_check.mjs")], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and " 0 failure(s)" in out.stdout, out.stdout[-1500:] + out.stderr[-500:]


def test_every_theme_is_defined_everywhere():
    css = (ROOT / "frontend/src/styles.css").read_text(encoding="utf8")
    theme_js = (ROOT / "frontend/src/theme.js").read_text(encoding="utf8")
    for key in app_settings.PALETTES:
        assert f'key: "{key}"' in theme_js, key
        if key in ("violet", "custom"):      # hand-tuned in styles.css / computed from one colour in customTheme.js
            continue
        block = re.search(r'\[data-palette="%s"\] \{(.*?)\}' % key, css, re.S).group(1)
        assert all(f"--p-{v}:" in block for v in ("a", "a-ink", "a-far", "b", "tint", "l", "l-ink", "l-far", "lb")) and "--ramp:" in block, key
        ramp_css = re.findall(r"#[0-9a-f]{6}", block.split("--ramp:")[1])
        ramp_js = re.findall(r"#[0-9a-f]{6}", re.search(r'key: "%s".*?ramp: \[(.*?)\]' % key, theme_js, re.S).group(1))
        assert ramp_css == ramp_js and len(ramp_css) == 10, key
