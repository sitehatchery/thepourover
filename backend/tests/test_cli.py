import pytest
from sqlalchemy import select

from app import cli
from app.auth.passwords import verify_password
from app.models import User

ADMIN_PASSWORD = "the-first-admins-password"
TYPED_PASSWORD = "typed-at-the-prompt-123"


def password_hash(session, username: str) -> str:
    session.expire_all()
    return session.scalar(select(User.password_hash).where(User.username == username))


def test_create_user_prompts_even_when_the_initial_password_is_set(settings, session, monkeypatch):
    # On the server CDP_INITIAL_PASSWORD always holds the first admin's password; a new user must not get it.
    monkeypatch.setenv("CDP_INITIAL_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": TYPED_PASSWORD)

    assert cli.main(["create-user", "tpo-reviewer", "--admin"]) == 0

    stored = password_hash(session, "tpo-reviewer")
    assert verify_password(TYPED_PASSWORD, stored) and not verify_password(ADMIN_PASSWORD, stored)


def test_start_up_script_reads_the_initial_password_only_when_asked(settings, session, monkeypatch):
    monkeypatch.setenv("CDP_INITIAL_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": pytest.fail("should not prompt"))

    assert cli.main(["create-user", "jason", "--admin", "--password-from-env"]) == 0
    assert verify_password(ADMIN_PASSWORD, password_hash(session, "jason"))


def test_password_from_env_without_the_variable_stops(settings, monkeypatch):
    monkeypatch.delenv("CDP_INITIAL_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["create-user", "jason", "--password-from-env"])
