from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import channel_hides, curation
from homefeed_core.channel_graph import (
    ChannelGraphSource,
    liked_channel_ids,
    refresh_suggestions,
    suggest,
    suggested_channels,
)
from homefeed_core.db import open_database
from homefeed_core.feeds import load_curation
from homefeed_core.gateway.fake import FakeGateway, make_channel
from homefeed_core.gateway.normalize import channel_from_info


def cid(letter: str) -> str:
    return "UC" + letter * 22


SEED = make_channel(cid("a"), title="Seed")
OTHER_SEED = make_channel(cid("b"), title="Other seed")
CHANNELS = [make_channel(cid(letter), title=f"Ch {letter}") for letter in "xyzw"]
X, Y, Z, W = CHANNELS
Q = make_channel(cid("q"), title="Quill")
R = make_channel(cid("r"), title="Reed")


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def gateway(sessions: sessionmaker[Session]) -> FakeGateway:
    gateway = FakeGateway()
    for channel in (SEED, OTHER_SEED, *CHANNELS, Q, R):
        gateway.add_channel(channel)
    gateway.add_featured(SEED.id, [X, Y, Z])
    gateway.add_featured(OTHER_SEED.id, [Y, W])
    # Second hop: Q is featured by X and Z, R by X; X also features a first-hop and a seed.
    gateway.add_featured(X.id, [Y, SEED, Q, R])
    gateway.add_featured(Z.id, [Q])
    for seed in (SEED, OTHER_SEED):
        with sessions.begin() as session:
            curation.subscribe(session, gateway, f"https://www.youtube.com/channel/{seed.id}")
            curation.update_channel(session, seed.id, prior="love")
    gateway.calls.clear()
    return gateway


def known(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    suggest(sessions, gateway)


def test_migration_creates_the_table(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        columns = session.execute(text("SELECT name FROM pragma_table_info('channel_hides')"))
        assert [row[0] for row in columns] == ["channel_id", "kind", "hidden_at"]


def test_hide_unhide_and_list(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    known(sessions, gateway)
    with sessions.begin() as session:
        first = channel_hides.hide(session, X.id, "dismissed")
        channel_hides.hide(session, Y.id, "dismissed")
        assert first is not None and first.title == "Ch x" and first.kind == "dismissed"
        assert channel_hides.hide(session, cid("q"), "dismissed") is None

    with sessions.begin() as session:
        # Blocking overrides dismissing; hiding again updates the time.
        again = channel_hides.hide(session, X.id, "blocked")
        assert again is not None and again.kind == "blocked"
        assert again.hidden_at >= first.hidden_at
        assert [h.channel_id for h in channel_hides.list_hides(session)] == [X.id, Y.id]
        assert channel_hides.unhide(session, X.id)
        assert not channel_hides.unhide(session, X.id)
        assert [h.channel_id for h in channel_hides.list_hides(session)] == [Y.id]
        with pytest.raises(ValueError):
            channel_hides.hide(session, Y.id, "nope")  # type: ignore[arg-type]


def test_hides_go_with_their_channel(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    known(sessions, gateway)
    with sessions.begin() as session:
        channel_hides.hide(session, X.id, "dismissed")
        session.execute(text("DELETE FROM channels WHERE id = :id"), {"id": X.id})
        assert channel_hides.list_hides(session) == []


def test_hidden_channels_are_not_suggested(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    known(sessions, gateway)
    with sessions.begin() as session:
        channel_hides.hide(session, Y.id, "dismissed")
        channel_hides.hide(session, X.id, "blocked")
        assert [s.channel_id for s in suggested_channels(session)] == [W.id, Z.id]
        channel_hides.unhide(session, Y.id)
        assert [s.channel_id for s in suggested_channels(session)][0] == Y.id


def test_blocked_channels_count_as_muted_for_the_ranker(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    known(sessions, gateway)
    with sessions.begin() as session:
        channel_hides.hide(session, X.id, "blocked")
        channel_hides.hide(session, Y.id, "dismissed")
        channel_hides.hide(session, SEED.id, "blocked")
        loaded = load_curation(session)
        assert loaded[X.id].muted
        assert Y.id not in loaded
        # A blocked subscription keeps its other preferences.
        assert loaded[SEED.id].muted and loaded[SEED.id].prior == "love"
        assert liked_channel_ids(session) == [OTHER_SEED.id]


def test_subscribing_clears_the_hide(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    known(sessions, gateway)
    with sessions.begin() as session:
        channel_hides.hide(session, X.id, "blocked")
    with sessions.begin() as session:
        curation.subscribe(session, gateway, f"https://www.youtube.com/channel/{X.id}")
        assert channel_hides.get_hide(session, X.id) is None
        assert X.id not in {c for c, v in load_curation(session).items() if v.muted}


def test_exclude_rotates_and_wraps(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    known(sessions, gateway)
    with sessions() as session:
        everything = [s.channel_id for s in suggested_channels(session, limit=None)]
        assert everything == [Y.id, X.id, W.id, Z.id]
        shown = everything[:2]
        assert [s.channel_id for s in suggested_channels(session, limit=2, exclude=shown)] == [
            W.id,
            Z.id,
        ]
        # Fewer unseen than the limit: wrap back to the top, never return fewer.
        three = suggested_channels(session, limit=3, exclude=shown)
        assert [s.channel_id for s in three] == [W.id, Z.id, Y.id]
        assert len(suggested_channels(session, limit=None, exclude=everything)) == 4


def test_refresh_suggestions_refetches_fresh_channels(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    known(sessions, gateway)
    assert len(gateway.calls) == 2
    suggest(sessions, gateway)
    assert len(gateway.calls) == 2  # cached

    gateway.add_featured(SEED.id, [X, Y, Z, W])
    result = refresh_suggestions(sessions, gateway, max_fetches=1)

    assert len(gateway.calls) == 3  # capped at one fetch
    assert len(result) == 4
    refresh_suggestions(sessions, gateway)
    assert len(gateway.calls) == 5


def test_channel_profile_fields_from_yt_dlp_info() -> None:
    info = {
        "channel_id": cid("a"),
        "channel": "Seed",
        "description": "About",
        "channel_follower_count": 1234,
        "thumbnails": [
            {"id": "banner_small", "url": "https://b/small", "width": 100},
            {"id": "banner_big", "url": "https://b/big", "width": 2000},
            {"id": "avatar_uncropped", "url": "https://a/avatar"},
        ],
    }
    channel = channel_from_info(info)
    assert channel.banner_url == "https://b/big"
    assert channel.thumbnail_url == "https://a/avatar"
    assert channel.subscriber_count == 1234
    assert channel.description == "About"

    info["thumbnails"].append({"id": "banner_uncropped", "url": "https://b/uncropped"})
    assert channel_from_info(info).banner_url == "https://b/uncropped"
    assert channel_from_info({"channel_id": cid("a")}).banner_url is None


def second_hop(sessions: sessionmaker[Session], gateway: FakeGateway, **kwargs: Any) -> list[str]:
    refresh_suggestions(sessions, gateway, second_hop=True, **kwargs)
    with sessions() as session:
        return [s.channel_id for s in suggested_channels(session, limit=None, second_hop=True)]


def test_second_hop_follows_the_first_with_attribution(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    known(sessions, gateway)
    with sessions() as session:  # nothing fetched for the suggestions yet
        assert len(suggested_channels(session, limit=None, second_hop=True)) == 4

    assert second_hop(sessions, gateway) == [Y.id, X.id, W.id, Z.id, Q.id, R.id]

    with sessions() as session:
        by_id = {s.channel_id: s for s in suggested_channels(session, limit=None, second_hop=True)}
        assert [r.channel_id for r in by_id[Q.id].featured_by] == [X.id, Z.id]
        assert [(r.channel_id, r.title) for r in by_id[R.id].featured_by] == [(X.id, "Ch x")]
        # The first hop alone is unchanged, and has no seeds or first-hop channels twice.
        assert [s.channel_id for s in suggested_channels(session, limit=None)] == [
            Y.id,
            X.id,
            W.id,
            Z.id,
        ]
        # Rotation applies over the combined list.
        rotated = suggested_channels(session, limit=3, exclude=[Y.id, X.id], second_hop=True)
        assert [s.channel_id for s in rotated] == [W.id, Z.id, Q.id]


def test_blocked_channels_are_neither_second_hop_targets_nor_sources(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    known(sessions, gateway)
    second_hop(sessions, gateway)
    with sessions.begin() as session:
        channel_hides.hide(session, Q.id, "blocked")
        channel_hides.hide(session, X.id, "blocked")  # R is only featured by X

    with sessions() as session:
        ids = [s.channel_id for s in suggested_channels(session, limit=None, second_hop=True)]
        assert ids == [Y.id, W.id, Z.id]


def test_refresh_crawls_suggestions_with_bounded_calls(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    known(sessions, gateway)
    gateway.calls.clear()

    refresh_suggestions(sessions, gateway, second_hop=True, max_hop_fetches=2, exclude=[Z.id])

    hops = [target for _op, target in gateway.calls[2:]]  # after the two seeds
    assert hops == [Z.id, Y.id]  # seen first, then top ranked
    refresh_suggestions(sessions, gateway, second_hop=True, max_hop_fetches=2)
    # Progresses: the two crawled are fresh now, so the next two are other channels.
    second = [target for _op, target in gateway.calls[4:] if target not in (SEED.id, OTHER_SEED.id)]
    assert second == [X.id, W.id]
    assert len(gateway.calls) == 2 * 2 + 2 + 2
    # Without second_hop nothing beyond the seeds is crawled.
    gateway.calls.clear()
    refresh_suggestions(sessions, gateway)
    assert len(gateway.calls) == 2


def test_channel_graph_source_stays_on_the_first_hop(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    known(sessions, gateway)
    second_hop(sessions, gateway)
    gateway.calls.clear()

    ChannelGraphSource(sessions, gateway, max_channels=10).fetch()

    uploads = {target for op, target in gateway.calls if op == "get_channel_uploads"}
    assert uploads == {Y.id, X.id, W.id, Z.id}
    gateway.calls.clear()
    ChannelGraphSource(sessions, gateway, max_channels=10, second_hop=True).fetch()
    uploads = {target for op, target in gateway.calls if op == "get_channel_uploads"}
    assert uploads == {Y.id, X.id, W.id, Z.id, Q.id, R.id}
