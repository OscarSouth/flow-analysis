"""Credential capture — .env edits must be surgical and the file stays private."""

from __future__ import annotations

import stat

from flow_analysis import auth


def test_adds_a_key_without_disturbing_the_others(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TRELLO_API_KEY=abc\nTRELLO_TOKEN=def\n")

    assert auth.set_env_value("GITHUB_TOKEN", "ghp_new", path=env) == "added"

    lines = env.read_text().splitlines()
    assert lines == ["TRELLO_API_KEY=abc", "TRELLO_TOKEN=def", "GITHUB_TOKEN=ghp_new"]


def test_replaces_in_place_rather_than_appending_a_duplicate(tmp_path):
    """Rotating a token must not leave the dead one behind.

    Whichever line the loader happened to read last would decide, silently.
    """
    env = tmp_path / ".env"
    env.write_text("GITHUB_TOKEN=old\nTRELLO_TOKEN=def\n")

    assert auth.set_env_value("GITHUB_TOKEN", "new", path=env) == "replaced"

    lines = env.read_text().splitlines()
    assert lines == ["GITHUB_TOKEN=new", "TRELLO_TOKEN=def"]
    assert lines.count("GITHUB_TOKEN=new") == 1


def test_comments_and_blank_lines_survive(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# how to get a token\n\nTRELLO_TOKEN=def\n")

    auth.set_env_value("GITHUB_TOKEN", "x", path=env)

    assert env.read_text().splitlines()[0] == "# how to get a token"


def test_file_is_owner_only(tmp_path):
    """A credential file that anyone on the machine can read is not a secret."""
    env = tmp_path / ".env"
    env.write_text("TRELLO_TOKEN=def\n")
    env.chmod(0o644)

    auth.set_env_value("GITHUB_TOKEN", "x", path=env)

    mode = stat.S_IMODE(env.stat().st_mode)
    assert mode == 0o600


def test_creates_the_file_when_absent(tmp_path):
    env = tmp_path / ".env"
    assert auth.set_env_value("GITHUB_TOKEN", "x", path=env) == "added"
    assert env.read_text() == "GITHUB_TOKEN=x\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
