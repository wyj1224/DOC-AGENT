from app import visitor


def test_signed_visitor_cookie_round_trip(monkeypatch):
    monkeypatch.setattr(visitor, "visitor_secret", lambda: "test-secret")
    visitor_key = "0123456789abcdef0123456789abcdef"

    cookie = visitor.sign_cookie(visitor_key)

    assert visitor.verify_cookie(cookie) == visitor_key


def test_tampered_visitor_cookie_is_rejected(monkeypatch):
    monkeypatch.setattr(visitor, "visitor_secret", lambda: "test-secret")
    visitor_key = "0123456789abcdef0123456789abcdef"
    cookie = visitor.sign_cookie(visitor_key)
    tampered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")

    assert visitor.verify_cookie(tampered) is None
    assert visitor.verify_cookie("not-a-cookie") is None
