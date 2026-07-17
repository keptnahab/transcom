from backend.auth.service import AuthService
import backend.config as cfg


def test_bootstrap_admin_and_login(tmp_path):
    auth = AuthService(tmp_path / "auth.db")
    bootstrap = auth.ensure_bootstrap_admin()
    assert bootstrap is not None
    email, password = bootstrap.split(":", 1)
    result = auth.login(email, password)
    assert result is not None
    assert result["user"]["is_admin"] is True
    assert auth.user_for_token(result["token"])["email"] == email
    auth.close()


def test_create_user_generates_password(tmp_path):
    auth = AuthService(tmp_path / "auth.db")
    created = auth.create_user("beta@example.com")
    assert created["password"]
    login = auth.login("beta@example.com", created["password"])
    assert login is not None
    assert login["user"]["is_admin"] is False
    assert auth.list_users()[0]["email"] == "beta@example.com"
    assert auth.list_users()[0]["password"] == created["password"]
    auth.close()


def test_admin_can_set_user_password(tmp_path):
    auth = AuthService(tmp_path / "auth.db")
    auth.create_user("beta@example.com")
    updated = auth.set_user_password("beta@example.com", "manualPass42")
    assert updated["password"] == "manualPass42"
    assert auth.list_users()[0]["password"] == "manualPass42"
    assert auth.login("beta@example.com", "manualPass42") is not None
    auth.close()


def test_admin_can_generate_replacement_password(tmp_path):
    auth = AuthService(tmp_path / "auth.db")
    created = auth.create_user("beta@example.com")
    updated = auth.set_user_password("beta@example.com")
    assert updated["password"]
    assert updated["password"] != created["password"]
    assert auth.login("beta@example.com", updated["password"]) is not None
    auth.close()


def test_auth_disabled_bypasses_login(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "AUTH_DISABLED", True)
    monkeypatch.setattr(cfg, "AUTH_DISABLED_EMAIL", "test@transcom.local")
    auth = AuthService(tmp_path / "auth.db")
    session = auth.login("", "")
    assert session is not None
    assert session["user"]["email"] == "test@transcom.local"
    assert session["user"]["is_admin"] is True
    assert auth.user_for_token(None)["email"] == "test@transcom.local"
    auth.close()
