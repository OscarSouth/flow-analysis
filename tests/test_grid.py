"""Offline tests: fabricate a board history and check the folding + metrics.

No network, no credentials. This is what proves the day-boundary rule, the
outcome classification, and the streak maths before any real data exists.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from flow_analysis import report, store
from flow_analysis.config import Config, ListRole
from flow_analysis.metrics import grid
from flow_analysis.metrics.calendar import flow_day
from flow_analysis.util import card_created_at

TZ = "Europe/London"
IN_ID, PROG_ID, OUT_ID = "list_in", "list_prog", "list_out"
LABEL_ID = "label_flow"
ACTIVITIES = ["Write", "Absorb", "Train", "Express", "Reveal"]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ACTIONS_PATH", tmp_path / "actions.jsonl")
    monkeypatch.setattr(store, "CARDS_PATH", tmp_path / "cards.jsonl")
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def make_config(start: date) -> Config:
    return Config(
        intent={},
        resolved={"board_id": "board1", "label_id": LABEL_ID},
        lists={
            "future": ListRole("future", "future", IN_ID),
            "present": ListRole("present", "present", PROG_ID),
            "past": ListRole("past", "past", OUT_ID),
        },
        activities=list(ACTIVITIES),
        descriptions={},
        label_name="Flow",
        label_colour="green",
        timezone=TZ,
        drain_at=time(4, 0),
        refill_at=time(6, 0),
        start_date=start,
    )


def card_id_at(moment: datetime, suffix: str) -> str:
    """Mimic a Mongo ObjectId: 8 hex chars of epoch, then 16 of anything."""
    return f"{int(moment.timestamp()):08x}{suffix:0>16}"


def spawn_moment(day: date, hour: int = 6) -> datetime:
    return datetime(
        day.year, day.month, day.day, hour, 0, tzinfo=ZoneInfo(TZ)
    ).astimezone(UTC)


def build_history(days: list[date], plan: dict[tuple[date, str], str]):
    """Plan maps (day, activity) -> 'completed' | 'started' | 'idle' | 'absent'."""
    cards, actions = [], []
    counter = 0
    for day in days:
        for activity in ACTIVITIES:
            state = plan.get((day, activity), "completed")
            if state == "absent":
                continue
            counter += 1
            spawned = spawn_moment(day)
            cid = card_id_at(spawned, f"{counter:x}")
            list_now = IN_ID
            actions.append(
                {
                    "id": f"a{counter}c",
                    "type": "createCard",
                    "date": spawned.isoformat().replace("+00:00", "Z"),
                    "data": {
                        "card": {"id": cid, "name": activity},
                        "list": {"id": IN_ID},
                    },
                }
            )
            if state in ("started", "completed"):
                started = spawned + timedelta(hours=3)
                list_now = PROG_ID
                actions.append(
                    {
                        "id": f"a{counter}s",
                        "type": "updateCard",
                        "date": started.isoformat().replace("+00:00", "Z"),
                        "data": {
                            "card": {"id": cid, "name": activity},
                            "listBefore": {"id": IN_ID},
                            "listAfter": {"id": PROG_ID},
                        },
                    }
                )
            if state == "completed":
                done = spawned + timedelta(hours=5)
                list_now = OUT_ID
                actions.append(
                    {
                        "id": f"a{counter}d",
                        "type": "updateCard",
                        "date": done.isoformat().replace("+00:00", "Z"),
                        "data": {
                            "card": {"id": cid, "name": activity},
                            "listBefore": {"id": PROG_ID},
                            "listAfter": {"id": OUT_ID},
                        },
                    }
                )
            cards.append(
                {
                    "id": cid,
                    "name": activity,
                    "idList": list_now,
                    "closed": state != "completed",
                    "labels": [{"id": LABEL_ID, "name": "Flow"}],
                }
            )
    return cards, actions


def seed(data_dir, cards, actions):
    store.append_actions(actions, set())
    store.append_cards(cards, set())


# --- util ------------------------------------------------------------------


def test_card_id_carries_creation_time():
    moment = datetime(2026, 8, 16, 5, 0, tzinfo=UTC)
    cid = card_id_at(moment, "1")
    assert card_created_at(cid) == moment


def test_flow_day_boundary_is_the_purge_time():
    boundary = time(4, 0)
    late_night = datetime(2026, 8, 17, 1, 30, tzinfo=ZoneInfo(TZ)).astimezone(UTC)
    morning = datetime(2026, 8, 17, 9, 0, tzinfo=ZoneInfo(TZ)).astimezone(UTC)
    # 01:30 belongs to the 16th: the purge has not run, the card is still there.
    assert flow_day(late_night, TZ, boundary) == date(2026, 8, 16)
    assert flow_day(morning, TZ, boundary) == date(2026, 8, 17)


# --- the fold -----------------------------------------------------------------


def test_outcomes_classified(data_dir):
    day = date(2026, 8, 10)
    plan = {
        (day, "Absorb"): "completed",
        (day, "Write"): "started",
        (day, "Reveal"): "idle",
        (day, "Train"): "absent",
        (day, "Express"): "completed",
    }
    cards, actions = build_history([day], plan)
    seed(data_dir, cards, actions)

    rows = {
        r.activity: r
        for r in grid.fold_rows(
            make_config(day), store.load_cards_latest(), store.load_actions()
        )
    }
    assert rows["Absorb"].outcome == grid.COMPLETED
    assert rows["Write"].outcome == grid.ABANDONED
    assert rows["Reveal"].outcome == grid.NEVER_STARTED
    assert rows["Train"].outcome == grid.NEVER_APPEARED
    assert rows["Express"].outcome == grid.COMPLETED

    assert rows["Absorb"].minutes_to_start == 180.0
    assert rows["Absorb"].minutes_to_complete == 300.0


def test_grid_is_dense_across_the_span(data_dir):
    days = [date(2026, 8, 1), date(2026, 8, 3)]  # 2nd missing entirely
    cards, actions = build_history(days, {})
    seed(data_dir, cards, actions)

    rows = grid.fold_rows(
        make_config(days[0]), store.load_cards_latest(), store.load_actions()
    )
    assert len(rows) == 3 * len(ACTIVITIES)
    missing = [r for r in rows if r.day == "2026-08-02"]
    assert {r.outcome for r in missing} == {grid.NEVER_APPEARED}


def flag_action(cid: str, activity: str, at: datetime, *, deep: bool, aid: str):
    """A completed-status toggle, as Trello records it (dueComplete old/new)."""
    return {
        "id": aid,
        "type": "updateCard",
        "date": at.isoformat().replace("+00:00", "Z"),
        "data": {
            "card": {"id": cid, "name": activity, "dueComplete": deep},
            "old": {"dueComplete": not deep},
        },
    }


def test_deep_flag_lands_on_the_cards_own_day(data_dir):
    """Retroactive flags attribute to the card's day, never the flag's date.

    The checkbox is a deep-dive judgment made whenever Oscar gets to it —
    the day after, from the archive — so attribution must ride card identity.
    Deep is orthogonal to outcome by decision: deep + abandoned is a real
    state, or deep engagement is penalised by the higher bar to completion.
    """
    day = date(2026, 8, 10)
    plan = {(day, "Absorb"): "completed", (day, "Write"): "started"}
    cards, actions = build_history([day], plan)
    by_name = {c["name"]: c["id"] for c in cards}
    next_day = spawn_moment(day + timedelta(days=1), hour=12)
    for aid, name in [("f1", "Absorb"), ("f2", "Write")]:
        actions.append(flag_action(by_name[name], name, next_day, deep=True, aid=aid))
    seed(data_dir, cards, actions)

    rows = {
        r.activity: r
        for r in grid.fold_rows(
            make_config(day), store.load_cards_latest(), store.load_actions()
        )
        if r.day == day.isoformat()
    }
    assert rows["Absorb"].deep
    assert rows["Absorb"].outcome == grid.COMPLETED
    assert rows["Write"].deep
    assert rows["Write"].outcome == grid.ABANDONED
    assert not rows["Train"].deep


def test_deep_flag_latest_toggle_wins(data_dir):
    """An unflag is a correction — the row reflects the current judgment."""
    day = date(2026, 8, 10)
    cards, actions = build_history([day], {})
    cid = next(c["id"] for c in cards if c["name"] == "Train")
    on = spawn_moment(day, hour=20)
    actions.append(flag_action(cid, "Train", on, deep=True, aid="f1"))
    actions.append(
        flag_action(cid, "Train", on + timedelta(minutes=5), deep=False, aid="f2")
    )
    seed(data_dir, cards, actions)

    rows = {
        r.activity: r
        for r in grid.fold_rows(
            make_config(day), store.load_cards_latest(), store.load_actions()
        )
    }
    assert not rows["Train"].deep


def test_deep_flag_falls_back_to_the_card_snapshot(data_dir):
    """A snapshot carrying dueComplete with no observed toggle still counts."""
    day = date(2026, 8, 10)
    cards, actions = build_history([day], {})
    for card in cards:
        if card["name"] == "Express":
            card["dueComplete"] = True
    seed(data_dir, cards, actions)

    rows = {
        r.activity: r
        for r in grid.fold_rows(
            make_config(day), store.load_cards_latest(), store.load_actions()
        )
    }
    assert rows["Express"].deep
    assert not rows["Write"].deep


def test_unlabelled_cards_are_ignored(data_dir):
    day = date(2026, 8, 10)
    cards, actions = build_history([day], {})
    cards.append(
        {
            "id": card_id_at(spawn_moment(day), "ff"),
            "name": "Absorb",
            "idList": IN_ID,
            "closed": False,
            "labels": [],  # a long-running card that happens to share a name
        }
    )
    seed(data_dir, cards, actions)
    rows = [
        r
        for r in grid.fold_rows(
            make_config(day), store.load_cards_latest(), store.load_actions()
        )
        if r.activity == "Absorb"
    ]
    assert len(rows) == 1
    assert rows[0].outcome == grid.COMPLETED


# --- report ----------------------------------------------------------------


def test_streaks_and_perfect_days(data_dir):
    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(5)]
    plan = {(days[2], "Write"): "idle"}  # one miss on day 3
    cards, actions = build_history(days, plan)
    seed(data_dir, cards, actions)

    cfg = make_config(days[0])
    summary = report.summarise(
        cfg, grid.fold_rows(cfg, store.load_cards_latest(), store.load_actions())
    )

    assert summary["n_days"] == 5
    assert summary["perfect_days"] == 4
    assert summary["perfect_streak_current"] == 2  # days 4 and 5
    assert summary["perfect_streak_longest"] == 2  # days 1-2, then 4-5
    assert summary["activities"]["Absorb"]["current_streak"] == 5
    assert summary["activities"]["Write"]["completed"] == 4
    assert summary["activities"]["Write"]["rate"] == 0.8
    assert summary["activities"]["Write"]["longest_streak"] == 2


def test_render_and_export(data_dir, tmp_path):
    days = [date(2026, 8, 1), date(2026, 8, 2)]
    cards, actions = build_history(days, {})
    seed(data_dir, cards, actions)

    cfg = make_config(days[0])
    rows = grid.fold_rows(cfg, store.load_cards_latest(), store.load_actions())
    text = report.render(report.summarise(cfg, rows), cfg)
    assert "Flow regularity" in text
    assert "Perfect days" in text

    out = tmp_path / "rows.csv"
    report.export(rows, out)
    assert out.read_text().count("\n") == len(rows) + 1


# --- store -----------------------------------------------------------------


def test_append_is_idempotent(data_dir):
    _cards, actions = build_history([date(2026, 8, 1)], {})
    known = set()
    first = store.append_actions(actions, known)
    second = store.append_actions(actions, known)
    assert first == len(actions)
    assert second == 0
    assert len(list(store.read_jsonl(store.ACTIONS_PATH))) == len(actions)


def test_card_snapshots_only_grow_on_change(data_dir):
    cards, _ = build_history([date(2026, 8, 1)], {})
    known = set()
    assert store.append_cards(cards, known) == len(cards)
    assert store.append_cards(cards, known) == 0

    assert cards[0]["idList"] == OUT_ID  # guard: the move below must be a real change
    moved = [{**cards[0], "idList": PROG_ID}]
    assert store.append_cards(moved, known) == 1

    latest = store.load_cards_latest()
    assert latest[cards[0]["id"]]["idList"] == PROG_ID


def test_integrity_does_not_demand_the_day_in_progress(data_dir):
    """start_date == today means no flow day has finished yet.

    There is nothing to be complete about, so this must not report a gap.
    """
    from datetime import date as _date

    from flow_analysis import sync

    store.save_state(
        {
            "newest_action_id": "x",
            "newest_action_date": "2026-01-01T00:00:00Z",
            "oldest_action_id": "y",
            "oldest_action_date": "2026-01-01T00:00:00Z",
        }
    )
    cfg = make_config(_date.today())
    report = sync.integrity(cfg)
    assert report["ok"] is True
    assert "No flow day has completed yet" in " ".join(report["notes"])


def test_state_round_trip(data_dir):
    store.save_state({"newest_action_id": "abc"})
    assert store.load_state()["newest_action_id"] == "abc"
    assert json.loads(store.STATE_PATH.read_text())["newest_action_id"] == "abc"
