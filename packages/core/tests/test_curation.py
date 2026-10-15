import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.curation import (
    KEYWORD_MAX_LENGTH,
    MAX_MUTE_DAYS,
    MUTE_WEIGHT,
    PRIOR_VALUES,
    PRIORS,
    SUBSCRIBE_WEIGHT,
    DuplicateKeywordMuteError,
    NotAChannelUrlError,
    TagSubscription,
    add_keyword_mute,
    delete_keyword_mute,
    get_channel,
    list_channels,
    list_keyword_mutes,
    list_tag_subscriptions,
    mute_tag,
    muted_keywords,
    muted_sql,
    relink_tag_subscription,
    subscribe,
    subscribe_tag,
    subscribed_channel_ids,
    tag_subscription,
    unmute_tag,
    unsubscribe,
    unsubscribe_tag,
    update_channel,
    update_keyword_mute,
    update_tag_subscription,
)
from homefeed_core.db import migrate, open_database
from homefeed_core.db.migrate import load_migrations
from homefeed_core.gateway import UnavailableError, UnsupportedUrlError
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.fake import FakeGateway, make_channel
from homefeed_core.tags import Tag, resolve_tag

WOOD = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")
BIRDS = make_channel("UC" + "b" * 22, title="birds", handle="@birds")
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(WOOD)
    gateway.add_channel(BIRDS)
    return gateway


def stored_channels(sessions: sessionmaker[Session]) -> list[tuple[str, str, str | None]]:
    with sessions() as session:
        rows = session.execute(text("SELECT id, title, handle FROM channels ORDER BY id"))
        return [tuple(row) for row in rows]


def test_subscribe_by_handle_url(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "https://www.youtube.com/@wood")

    assert created is True
    assert channel.channel_id == WOOD.id
    assert channel.title == "Woodworking"
    assert channel.handle == "@wood"
    assert (channel.prior, channel.pinned, channel.muted) == ("neutral", False, False)
    assert channel.subscribed_at.endswith("Z")
    assert gateway.calls == [("resolve_url", "https://www.youtube.com/@wood")]
    assert stored_channels(sessions) == [(WOOD.id, "Woodworking", "@wood")]
    with sessions() as session:
        assert get_channel(session, WOOD.id) == channel
        assert subscribed_channel_ids(session) == [WOOD.id]


def test_subscribe_again_keeps_prefs_and_refreshes_channel(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, f"https://www.youtube.com/channel/{WOOD.id}")
        update_channel(session, WOOD.id, prior="love", pinned=True)
    gateway.add_channel(make_channel(WOOD.id, title="Wood Shop", handle="@wood"))

    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "@wood")

    assert created is False
    assert (channel.title, channel.prior, channel.pinned) == ("Wood Shop", "love", True)
    assert stored_channels(sessions) == [(WOOD.id, "Wood Shop", "@wood")]


def test_subscribe_updates_a_channel_already_known(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        session.execute(text(f"INSERT INTO channels (id, title) VALUES ('{WOOD.id}', 'Old')"))

    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "@wood")

    assert created is True
    assert channel.title == "Woodworking"
    assert stored_channels(sessions) == [(WOOD.id, "Woodworking", "@wood")]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/playlist?list=PL0123456789",
    ],
)
def test_subscribe_rejects_non_channel_urls(
    sessions: sessionmaker[Session], gateway: FakeGateway, url: str
) -> None:
    with pytest.raises(NotAChannelUrlError), sessions.begin() as session:
        subscribe(session, gateway, url)
    assert stored_channels(sessions) == []


def test_subscribe_passes_gateway_errors_through(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with pytest.raises(UnsupportedUrlError), sessions.begin() as session:
        subscribe(session, gateway, "https://example.com/@wood")
    with pytest.raises(UnavailableError), sessions.begin() as session:
        subscribe(session, gateway, "https://www.youtube.com/@nobody")
    assert stored_channels(sessions) == []


def test_list_channels_pinned_first_then_by_title(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        subscribe(session, gateway, "@birds")
    with sessions() as session:
        assert [c.title for c in list_channels(session)] == ["birds", "Woodworking"]
    with sessions.begin() as session:
        update_channel(session, WOOD.id, pinned=True)
    with sessions() as session:
        assert [c.title for c in list_channels(session)] == ["Woodworking", "birds"]


def test_update_channel_changes_only_given_fields(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        before, _ = subscribe(session, gateway, "@wood")
    time.sleep(0.01)  # timestamps have millisecond resolution

    with sessions.begin() as session:
        muted = update_channel(session, WOOD.id, muted=True)
        skeptical = update_channel(session, WOOD.id, prior="skeptical")
        unchanged = update_channel(session, WOOD.id)

    assert muted is not None and (muted.prior, muted.pinned, muted.muted) == (
        "neutral",
        False,
        True,
    )
    assert skeptical is not None and (skeptical.prior, skeptical.muted) == ("skeptical", True)
    assert unchanged == skeptical
    assert skeptical.updated_at > before.updated_at
    assert skeptical.subscribed_at == before.subscribed_at


def test_a_new_subscription_is_neither_on_trial_nor_muted_for_a_time(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        channel, _ = subscribe(session, gateway, "@wood")

    assert (channel.muted_until, channel.trial_until) == (None, None)


def test_mute_for_days_sets_an_end_time_that_stops_being_reported_once_it_passes(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        muted = update_channel(session, WOOD.id, mute_days=30, now=NOW)

    assert muted is not None
    assert (muted.muted, muted.muted_until) == (False, "2026-11-11T06:00:00.000Z")
    with sessions() as session:
        last_day = get_channel(session, WOOD.id, now=NOW + timedelta(days=29, hours=23))
        over = get_channel(session, WOOD.id, now=NOW + timedelta(days=30))
        assert last_day is not None and last_day.muted_until == "2026-11-11T06:00:00.000Z"
        assert over is not None and (over.muted, over.muted_until) == (False, None)
        assert [c.muted_until for c in list_channels(session, now=NOW)] == [
            "2026-11-11T06:00:00.000Z"
        ]
        assert [c.muted_until for c in list_channels(session, now=NOW + timedelta(days=31))] == [
            None
        ]


def test_the_kinds_of_mute_replace_each_other(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        for_good = update_channel(session, WOOD.id, muted=True, now=NOW)
        for_a_time = update_channel(session, WOOD.id, mute_days=7, now=NOW)
        for_good_again = update_channel(session, WOOD.id, muted=True, now=NOW)
        update_channel(session, WOOD.id, mute_days=7, now=NOW)
        unmuted = update_channel(session, WOOD.id, muted=False, now=NOW)

    assert for_good is not None and (for_good.muted, for_good.muted_until) == (True, None)
    assert for_a_time is not None and (for_a_time.muted, for_a_time.muted_until) == (
        False,
        "2026-10-19T06:00:00.000Z",
    )
    assert for_good_again is not None and (for_good_again.muted, for_good_again.muted_until) == (
        True,
        None,
    )
    assert unmuted is not None and (unmuted.muted, unmuted.muted_until) == (False, None)


def test_changing_other_preferences_keeps_a_timed_mute(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        update_channel(session, WOOD.id, mute_days=30, now=NOW)
        changed = update_channel(session, WOOD.id, prior="love", pinned=True, now=NOW)

    assert changed is not None
    assert (changed.prior, changed.pinned, changed.muted_until) == (
        "love",
        True,
        "2026-11-11T06:00:00.000Z",
    )


@pytest.mark.parametrize("days", [0, -1, MAX_MUTE_DAYS + 1])
def test_mute_for_days_must_be_in_range(
    sessions: sessionmaker[Session], gateway: FakeGateway, days: int
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        with pytest.raises(ValueError, match="mute_days"):
            update_channel(session, WOOD.id, mute_days=days)


def test_muted_and_mute_days_cannot_be_given_together(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        with pytest.raises(ValueError, match="either"):
            update_channel(session, WOOD.id, muted=True, mute_days=7)


def test_muted_sql_matches_both_kinds_of_mute_until_they_run_out(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        subscribe(session, gateway, "@birds")
    query = text(f"SELECT p.channel_id FROM channel_prefs AS p WHERE {muted_sql('p')}")

    def muted_at(now: datetime) -> set[str]:
        with sessions() as session:
            return set(session.execute(query, {"now": format_timestamp(now)}).scalars())

    assert muted_at(NOW) == set()
    with sessions.begin() as session:
        update_channel(session, WOOD.id, muted=True)
        update_channel(session, BIRDS.id, mute_days=3, now=NOW)
    assert muted_at(NOW) == {WOOD.id, BIRDS.id}
    assert muted_at(NOW + timedelta(days=3)) == {WOOD.id}


def test_update_unknown_channel_returns_none(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert update_channel(session, WOOD.id, pinned=True) is None


def test_unsubscribe_keeps_the_channel(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        update_channel(session, WOOD.id, prior="love")
    with sessions.begin() as session:
        assert unsubscribe(session, WOOD.id) is True
        assert unsubscribe(session, WOOD.id) is False

    with sessions() as session:
        assert list_channels(session) == []
        assert get_channel(session, WOOD.id) is None
    assert stored_channels(sessions) == [(WOOD.id, "Woodworking", "@wood")]

    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "@wood")
    assert created is True and channel.prior == "neutral"


def test_priors_have_plan_values() -> None:
    assert PRIORS == ("love", "like", "neutral", "skeptical")
    assert PRIOR_VALUES == {"love": 0.8, "like": 0.4, "neutral": 0.0, "skeptical": -0.4}


def test_table_rejects_invalid_prior_and_unknown_channel(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text(f"INSERT INTO channels (id, title) VALUES ('{WOOD.id}', 'W')"))
        session.execute(
            text(f"INSERT INTO channel_prefs (channel_id, prior) VALUES ('{WOOD.id}', 'meh')")
        )
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text("INSERT INTO channel_prefs (channel_id) VALUES ('UCmissing')"))


def test_keyword_mutes_crud(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        crypto, created = add_keyword_mute(session, "  crypto  ")
        reaction, _ = add_keyword_mute(session, "reaction\tvideo")

    assert created is True
    assert crypto.keyword == "crypto"
    assert reaction.keyword == "reaction video"
    assert crypto.created_at.endswith("Z")
    with sessions.begin() as session:
        assert list_keyword_mutes(session) == [crypto, reaction]
        renamed = update_keyword_mute(session, reaction.id, "Reaction")
        assert renamed is not None
        assert (renamed.id, renamed.keyword) == (reaction.id, "Reaction")
        assert muted_keywords(session) == ["crypto", "Reaction"]
        assert delete_keyword_mute(session, crypto.id) is True
        assert delete_keyword_mute(session, crypto.id) is False
        assert update_keyword_mute(session, crypto.id, "gone") is None
        assert muted_keywords(session) == ["Reaction"]


def test_keyword_mutes_are_unique_ignoring_case(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        crypto, _ = add_keyword_mute(session, "Crypto")
        again, created = add_keyword_mute(session, "CRYPTO")
        nft, _ = add_keyword_mute(session, "nft")

        assert created is False
        assert again == crypto
        with pytest.raises(DuplicateKeywordMuteError):
            update_keyword_mute(session, nft.id, "crypto")
        # Changing only the case of a mute's own keyword is fine.
        assert update_keyword_mute(session, crypto.id, "crypto") is not None
        assert muted_keywords(session) == ["crypto", "nft"]


@pytest.mark.parametrize("keyword", ["", "   ", "x" * (KEYWORD_MAX_LENGTH + 1)])
def test_keyword_mute_rejects_blank_and_long_keywords(
    sessions: sessionmaker[Session], keyword: str
) -> None:
    with sessions.begin() as session:
        with pytest.raises(ValueError):
            add_keyword_mute(session, keyword)
        assert list_keyword_mutes(session) == []


def make_tag(session: Session, label: str) -> Tag:
    tag = resolve_tag(session, label)
    assert tag is not None
    return tag


def test_subscribe_tag(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rust = make_tag(session, "Rust")
        subscription, created = subscribe_tag(session, rust, now=NOW)
        again, created_again = subscribe_tag(session, rust, weight=0.9, now=NOW)

    assert created and not created_again
    assert again == subscription  # an existing subscription is left as it is
    assert subscription == TagSubscription(
        tag_id=rust.id,
        slug="rust",
        label="Rust",
        weight=SUBSCRIBE_WEIGHT,
        hide=False,
        created_at="2026-10-12T06:00:00.000Z",
        updated_at="2026-10-12T06:00:00.000Z",
    )
    assert not subscription.muted
    with sessions.begin() as session:
        assert tag_subscription(session, rust.id) == subscription
        assert list_tag_subscriptions(session) == [subscription]
        assert unsubscribe_tag(session, rust.id) is True
        assert unsubscribe_tag(session, rust.id) is False
        assert tag_subscription(session, rust.id) is None
        assert list_tag_subscriptions(session) == []


def test_tag_subscriptions_list_by_label(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        for label in ("woodworking", "Birds", "chess"):
            subscribe_tag(session, make_tag(session, label))
        mute_tag(session, make_tag(session, "drama"))
        labels = [s.label for s in list_tag_subscriptions(session)]

    assert labels == ["Birds", "chess", "drama", "woodworking"]


def test_update_tag_subscription_weight(sessions: sessionmaker[Session]) -> None:
    later = NOW + timedelta(days=1)
    with sessions.begin() as session:
        rust = make_tag(session, "rust")
        subscribe_tag(session, rust, now=NOW)
        moved = update_tag_subscription(session, rust.id, weight=0.8, now=later)
        assert moved is not None
        assert (moved.weight, moved.updated_at) == (0.8, "2026-10-13T06:00:00.000Z")
        assert update_tag_subscription(session, 999, weight=0.1) is None
        for weight in (1.01, -2):
            with pytest.raises(ValueError, match="between -1 and 1"):
                update_tag_subscription(session, rust.id, weight=weight)
            with pytest.raises(ValueError, match="between -1 and 1"):
                subscribe_tag(session, make_tag(session, "go"), weight=weight)
        assert tag_subscription(session, rust.id) == moved


def test_deleting_a_tag_deletes_its_subscription(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rust = make_tag(session, "rust")
        subscribe_tag(session, rust)
        session.execute(text("DELETE FROM tags WHERE id = :id"), {"id": rust.id})
        assert list_tag_subscriptions(session) == []


def test_relink_tag_subscription_follows_a_merge(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        old, new, other = (make_tag(session, label) for label in ("rust-lang", "rust", "go"))
        subscribe_tag(session, old, weight=0.7)
        relink_tag_subscription(session, old.id, new.id)  # the target has none: it follows
        assert tag_subscription(session, old.id) is None
        moved = tag_subscription(session, new.id)
        assert moved is not None and moved.weight == 0.7

        relink_tag_subscription(session, other.id, new.id)  # the source has none
        assert tag_subscription(session, new.id) == moved

        subscribe_tag(session, other, weight=-1)
        relink_tag_subscription(session, other.id, new.id)  # both have one: the target's stands
        assert tag_subscription(session, other.id) is None
        assert tag_subscription(session, new.id) == moved


def test_mute_tag_makes_a_negative_subscription_or_flips_one(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        rust, go = make_tag(session, "rust"), make_tag(session, "go")
        muted = mute_tag(session, rust, now=NOW)
        subscribe_tag(session, go, now=NOW)
        flipped = mute_tag(session, go, now=NOW)
        update_tag_subscription(session, rust.id, weight=-0.9, now=NOW)
        kept = mute_tag(session, rust, now=NOW)  # already muted: left alone

        assert (muted.weight, muted.hide, muted.muted) == (MUTE_WEIGHT, False, True)
        assert (flipped.weight, flipped.tag_id) == (MUTE_WEIGHT, go.id)
        assert kept.weight == -0.9
        assert unmute_tag(session, rust.id) is True
        assert unmute_tag(session, rust.id) is False
        assert tag_subscription(session, rust.id) is None


def test_unmute_leaves_subscriptions_alone(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rust = make_tag(session, "rust")
        subscribe_tag(session, rust, now=NOW)

        assert unmute_tag(session, rust.id) is False
        assert tag_subscription(session, rust.id) is not None


def test_hide_needs_weight_minus_one(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rust = make_tag(session, "rust")
        mute_tag(session, rust, now=NOW)

        with pytest.raises(ValueError, match="weight -1"):
            update_tag_subscription(session, rust.id, hide=True)  # weight is -0.5
        with pytest.raises(ValueError, match="weight -1"):
            update_tag_subscription(session, rust.id, weight=0.2, hide=True)

        hidden = update_tag_subscription(session, rust.id, weight=-1, hide=True, now=NOW)
        assert hidden is not None and hidden.hide
        # Setting -1 again keeps it.
        again = update_tag_subscription(session, rust.id, weight=-1)
        assert again is not None and again.hide
        # Any other weight clears it, and it stays off when the weight returns to -1.
        raised = update_tag_subscription(session, rust.id, weight=-0.9, now=NOW)
        assert raised is not None and not raised.hide
        back = update_tag_subscription(session, rust.id, weight=-1, now=NOW)
        assert back is not None and not back.hide
        shown = update_tag_subscription(session, rust.id, hide=False)
        assert shown is not None and not shown.hide
        # The table refuses a hidden row at another weight.
        with pytest.raises(IntegrityError):
            session.execute(
                text("UPDATE tag_subscriptions SET weight = -0.5, hide = 1 WHERE tag_id = :id"),
                {"id": rust.id},
            )


def test_migration_carries_topics_over_to_tag_subscriptions(tmp_path: Path) -> None:
    """0025 keeps tag-backed topics (and topics named like a tag) as subscriptions and
    drops the topics table."""
    path = tmp_path / "homefeed.sqlite"
    migrations = load_migrations()
    migrate(path, [m for m in migrations if m.version < 25])
    conn = sqlite3.connect(path)
    with conn:
        conn.executemany(
            "INSERT INTO tags (id, slug, label) VALUES (?, ?, ?)",
            [
                (1, "rust", "Rust"),
                (2, "drama", "drama"),
                (3, "hand-tools", "Hand tools"),
                (4, "f1", "F1"),
                (5, "chess", "Chess"),
            ],
        )
        conn.executemany(
            "INSERT INTO tag_aliases (alias, tag_id, source) VALUES (?, ?, 'user')",
            [("formula-1", 4), ("rust-lang", 1)],
        )
        topics = [
            # name, description, weight, decay, tag_id, match_mode, hide
            ("Rust", "Rust", 0.5, 0, 1, "tag", 0),
            ("drama", "drama", -1.0, 0, 2, "both", 1),
            ("Hand tools", "Woodworking with hand tools", 0.8, 1, None, "embedding", 0),
            ("Formula 1", "Motor racing", -0.3, 0, None, "embedding", 0),
            ("Rust lang", "The language", 0.9, 0, None, "embedding", 0),  # Rust has one
            ("Chess", "Board games", 0.0, 0, None, "embedding", 0),  # weight 0: nothing
            ("Gardening", "Growing vegetables", 0.6, 0, None, "embedding", 0),  # no such tag
        ]
        for index, (name, description, weight, decay, tag_id, mode, hide) in enumerate(topics):
            conn.execute(
                """
                INSERT INTO topics (name, description, embedding, embedding_model, weight,
                                    decay, tag_id, match_mode, hide, created_at)
                VALUES (?, ?, x'00', 'stub', ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    weight,
                    decay,
                    tag_id,
                    mode,
                    hide,
                    f"2026-01-0{index + 1}T00:00:00.000Z",
                ),
            )
    conn.close()

    migrate(path, migrations)

    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT tag_id, weight, hide, created_at FROM tag_subscriptions ORDER BY tag_id"
    ).fetchall()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert rows == [
        (1, 0.5, 0, "2026-01-01T00:00:00.000Z"),
        (2, -1.0, 1, "2026-01-02T00:00:00.000Z"),
        (3, 0.8, 0, "2026-01-03T00:00:00.000Z"),
        (4, -0.3, 0, "2026-01-04T00:00:00.000Z"),
    ]
    assert "topics" not in tables
