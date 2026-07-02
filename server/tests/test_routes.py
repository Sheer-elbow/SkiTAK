"""Plugin blueprint wiring and anonymous surface behaviour."""
from __future__ import annotations


def test_plugin_registers_expected_routes(app):
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/skitak/sessions" in rules
    assert "/api/skitak/sessions/<session_id>/teams/<team_id>/invite" in rules
    assert "/api/skitak/clients" in rules
    assert "/api/skitak/enroll/<token>" in rules
    assert "/api/skitak/enroll/<token>/package" in rules
    assert "/join/<token>" in rules
    assert "/api/skitak/health" in rules


def test_health_is_anonymous(client):
    resp = client.get("/api/skitak/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_enroll_rejects_malformed_tokens(client):
    # Malformed tokens must be rejected before touching the DB or CA
    resp = client.get("/api/skitak/enroll/short")
    assert resp.status_code == 410
    resp = client.get("/api/skitak/enroll/../../../etc/passwd")
    assert resp.status_code in (404, 410)


def test_join_page_rejects_malformed_tokens(client):
    assert client.get("/join/<script>alert(1)</script>").status_code == 404
    assert client.get("/join/short").status_code == 404


def test_join_page_renders_for_valid_token_shape(client):
    resp = client.get("/join/" + "a" * 43)
    assert resp.status_code == 200
    assert b"Join SkiTAK" in resp.data


def test_guide_endpoints_require_auth(client):
    """Session/client management must not be reachable anonymously."""
    for method, path in [
        ("GET",  "/api/skitak/sessions"),
        ("POST", "/api/skitak/sessions"),
        ("GET",  "/api/skitak/clients"),
        ("POST", "/api/skitak/clients"),
    ]:
        resp = client.open(path, method=method, json={})
        assert resp.status_code in (302, 401, 403), f"{method} {path} returned {resp.status_code}"
