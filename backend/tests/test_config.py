"""Config (.env parsing + settings) unit tests."""

import textwrap

from backend.app.config import (
    from_env,
    load_dotenv,
    parse_dotenv_text,
    reset_dotenv_cache,
)


def test_parse_dotenv_text_quotes_comments_blanks() -> None:
    text = textwrap.dedent(
        """\
        # comment
        DATABASE_URL=sqlite:///x.db

        QUOTED="a=b"
        SINGLE='spaced value'
        TRAILING=plain # stripped note
        EMPTY=
        NOEQUALS
        """
    )
    assert parse_dotenv_text(text) == {
        "DATABASE_URL": "sqlite:///x.db",
        "QUOTED": "a=b",
        "SINGLE": "spaced value",
        "TRAILING": "plain",
        "EMPTY": "",
    }


def test_load_dotenv_never_overrides_real_env(tmp_path, monkeypatch) -> None:
    import os

    env_file = tmp_path / ".env"
    env_file.write_text("SIM_SEED=7\nFRD_TEST_GAP=9001\n", encoding="utf-8")
    monkeypatch.setenv("SIM_SEED", "99")
    reset_dotenv_cache()
    try:
        assert load_dotenv(env_file) == str(env_file)
        assert os.environ["SIM_SEED"] == "99"  # real env wins
        assert os.environ["FRD_TEST_GAP"] == "9001"  # .env fills the gap
    finally:
        os.environ.pop("FRD_TEST_GAP", None)
        reset_dotenv_cache()


def test_load_dotenv_missing_file_is_noop(tmp_path) -> None:
    reset_dotenv_cache()
    try:
        assert load_dotenv(tmp_path / "absent.env") is None
    finally:
        reset_dotenv_cache()


def test_from_env_defaults_and_bad_ints(monkeypatch) -> None:
    for key in ("DATABASE_URL", "SIM_SEED", "HOST", "PORT", "CORS_ORIGINS", "SNAPSHOT_EVERY"):
        monkeypatch.delenv(key, raising=False)
    settings = from_env()
    assert settings.database_url == ""
    assert (settings.sim_seed, settings.host, settings.port) == (42, "127.0.0.1", 8000)
    assert settings.snapshot_every == 10
    assert "http://localhost:3000" in settings.cors_origins

    monkeypatch.setenv("SIM_SEED", "not-an-int")
    monkeypatch.setenv("PORT", "abc")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    settings = from_env()
    assert (settings.sim_seed, settings.port) == (42, 8000)
    assert settings.cors_origins == ["https://a.example", "https://b.example"]
    assert settings.database_url == "sqlite:///x.db"
