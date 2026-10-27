from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import admin


def use_token(monkeypatch, token: str) -> None:
    monkeypatch.setattr(admin, "get_settings", lambda: SimpleNamespace(admin_token=token))


def test_guard_is_open_without_configured_token(monkeypatch):
    use_token(monkeypatch, "")
    admin.require_admin("")


def test_correct_token_is_accepted(monkeypatch):
    use_token(monkeypatch, "s3cret")
    admin.require_admin("s3cret")


@pytest.mark.parametrize("sent", ["", "wrong", "s3cret "])
def test_missing_or_wrong_token_is_rejected(monkeypatch, sent):
    use_token(monkeypatch, "s3cret")
    with pytest.raises(HTTPException) as exc:
        admin.require_admin(sent)
    assert exc.value.status_code == 401


def test_admin_routes_are_guarded():
    from app.routers import excel, templates

    guarded = {
        (route.path, method)
        for router in (excel.router, templates.router)
        for route in router.routes
        for method in route.methods
        if any(dep.dependency is admin.require_admin for dep in route.dependencies)
    }
    assert guarded == {
        ("/excel/ingest", "POST"),
        ("/templates/upload", "POST"),
        ("/templates/{template_id}", "DELETE"),
    }
