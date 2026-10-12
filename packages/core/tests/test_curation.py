import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.curation import (
    KEYWORD_MAX_LENGTH,
    PRIOR_VALUES,
    PRIORS,
    TOPIC_DESCRIPTION_MAX_LENGTH,
    TOPIC_NAME_MAX_LENGTH,
    DuplicateKeywordMuteError,
    DuplicateTopicError,
    NotAChannelUrlError,
    add_keyword_mute,
    add_topic,
    decayed_weight,
    delete_keyword_mute,
    delete_topic,
    get_channel,
    get_topic,
    list_channels,
    list_keyword_mutes,
    list_topics,
    muted_keywords,
    reaffirm_topic,
    refresh_topic_embeddings,
    subscribe,
    subscribed_channel_ids,
    topic_vectors,
    unsubscribe,
    update_channel,
    update_keyword_mute,
    update_topic,
)
from homefeed_core.db import open_database
from homefeed_core.embeddings import StubEmbeddingProvider
from homefeed_core.gateway import UnavailableError, UnsupportedUrlError
from homefeed_core.gateway.fake import FakeGateway, make_channel

WOOD = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")
BIRDS = make_channel("UC" + "b" * 22, title="birds", handle="@birds")


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


NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


@pytest.fixture
def embedder() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


def test_topics_crud(sessions: sessionmaker[Session], embedder: StubEmbeddingProvider) -> None:
    with sessions.begin() as session:
        wood = add_topic(
            session,
            embedder,
            name="  Hand   tools ",
            description=" Woodworking with hand tools ",
            weight=0.8,
            now=NOW,
        )
        drama = add_topic(
            session,
            embedder,
            name="drama",
            description="Influencer drama",
            weight=-1,
            decay=True,
            now=NOW,
        )

    assert (wood.name, wood.description, wood.weight, wood.decay) == (
        "Hand tools",
        "Woodworking with hand tools",
        0.8,
        False,
    )
    assert wood.effective_weight == 0.8
    assert wood.reaffirmed_at == wood.created_at == "2026-10-12T06:00:00.000Z"
    assert embedder.calls == [["Woodworking with hand tools"], ["Influencer drama"]]
    with sessions.begin() as session:
        assert list_topics(session, now=NOW) == [drama, wood]  # alphabetical, ignoring case
        renamed = update_topic(session, embedder, wood.id, name="Chisels", now=NOW)
        assert renamed is not None and renamed.name == "Chisels"
        assert delete_topic(session, drama.id) is True
        assert delete_topic(session, drama.id) is False
        assert update_topic(session, embedder, drama.id, weight=0.1) is None
        assert reaffirm_topic(session, drama.id) is None
        assert get_topic(session, drama.id) is None
        assert [t.name for t in list_topics(session)] == ["Chisels"]
    assert len(embedder.calls) == 2  # renaming doesn't embed


def test_topic_names_are_unique_ignoring_case(
    sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    with sessions.begin() as session:
        wood = add_topic(session, embedder, name="Woodworking", description="wood", weight=1)
        birds = add_topic(session, embedder, name="Birds", description="birds", weight=1)

        with pytest.raises(DuplicateTopicError):
            add_topic(session, embedder, name="WOODWORKING", description="other", weight=1)
        with pytest.raises(DuplicateTopicError):
            update_topic(session, embedder, birds.id, name="woodworking")
        # Changing only the case of a topic's own name is fine.
        renamed = update_topic(session, embedder, wood.id, name="woodworking")
        assert renamed is not None and renamed.name == "woodworking"


@pytest.mark.parametrize(
    "fields",
    [
        {"name": " "},
        {"name": "x" * (TOPIC_NAME_MAX_LENGTH + 1)},
        {"description": "  "},
        {"description": "x" * (TOPIC_DESCRIPTION_MAX_LENGTH + 1)},
        {"weight": 1.01},
        {"weight": -2},
    ],
)
def test_topics_reject_invalid_fields(
    sessions: sessionmaker[Session], embedder: StubEmbeddingProvider, fields: dict[str, Any]
) -> None:
    valid: dict[str, Any] = {"name": "Wood", "description": "Woodworking", "weight": 0.5}
    with sessions.begin() as session:
        with pytest.raises(ValueError):
            add_topic(session, embedder, **{**valid, **fields})
        topic = add_topic(session, embedder, **valid)
        with pytest.raises(ValueError):
            update_topic(session, embedder, topic.id, **fields)
        assert list_topics(session) == [topic]


def test_changing_the_description_embeds_it_again(
    sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    with sessions.begin() as session:
        topic = add_topic(session, embedder, name="Wood", description="Woodworking", weight=1)
        update_topic(session, embedder, topic.id, description=" Woodworking ")  # unchanged
        update_topic(session, embedder, topic.id, description="Timber framing")
        [vector] = topic_vectors(session)

    assert embedder.calls == [["Woodworking"], ["Timber framing"]]
    assert vector.embedding == pytest.approx(embedder.embed(["Timber framing"])[0], abs=1e-6)


def test_decayed_weight_halves_every_30_days() -> None:
    def at(days: float, *, decay: bool = True) -> float:
        return decayed_weight(0.8, decay=decay, reaffirmed_at=NOW, now=NOW + timedelta(days=days))

    assert at(0) == 0.8
    assert at(30) == pytest.approx(0.4)
    assert at(60) == pytest.approx(0.2)
    assert at(15) == pytest.approx(0.8 / 2**0.5)
    assert at(60, decay=False) == 0.8
    assert at(-1) == 0.8  # a clock running behind doesn't grow the weight


def test_decaying_topics_weaken_until_reaffirmed(
    sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    later = NOW + timedelta(days=30)
    with sessions.begin() as session:
        topic = add_topic(
            session, embedder, name="Wood", description="wood", weight=0.8, decay=True, now=NOW
        )
        steady = add_topic(
            session, embedder, name="Birds", description="birds", weight=0.5, now=NOW
        )

        decayed = get_topic(session, topic.id, now=later)
        assert decayed is not None and decayed.effective_weight == pytest.approx(0.4)
        assert decayed.weight == 0.8
        assert [(v.name, v.weight) for v in topic_vectors(session, now=later)] == [
            ("Wood", pytest.approx(0.4)),
            ("Birds", 0.5),
        ]
        assert steady.id != topic.id

        reaffirmed = reaffirm_topic(session, topic.id, now=later)
        assert reaffirmed is not None
        assert reaffirmed.effective_weight == pytest.approx(0.8)
        assert reaffirmed.reaffirmed_at == "2026-11-11T06:00:00.000Z"


def test_setting_the_weight_or_turning_decay_on_reaffirms(
    sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    day = timedelta(days=1)
    with sessions.begin() as session:
        topic = add_topic(session, embedder, name="Wood", description="wood", weight=0.8, now=NOW)

        renamed = update_topic(session, embedder, topic.id, name="Timber", now=NOW + day)
        assert renamed is not None and renamed.reaffirmed_at == topic.reaffirmed_at
        decaying = update_topic(session, embedder, topic.id, decay=True, now=NOW + 2 * day)
        assert decaying is not None and decaying.reaffirmed_at == "2026-10-14T06:00:00.000Z"
        again = update_topic(session, embedder, topic.id, decay=True, now=NOW + 3 * day)
        assert again is not None and again.reaffirmed_at == decaying.reaffirmed_at
        moved = update_topic(session, embedder, topic.id, weight=-0.2, now=NOW + 4 * day)
        assert moved is not None
        assert (moved.weight, moved.effective_weight) == (-0.2, -0.2)
        assert moved.reaffirmed_at == moved.updated_at == "2026-10-16T06:00:00.000Z"


def test_refresh_topic_embeddings_after_a_model_change(
    sessions: sessionmaker[Session], embedder: StubEmbeddingProvider
) -> None:
    with sessions.begin() as session:
        wood = add_topic(session, embedder, name="Wood", description="wood", weight=1)
        add_topic(session, embedder, name="Birds", description="birds", weight=1)
    other = StubEmbeddingProvider("stub-embedding-v2", vectors={"wood": [1.0] + [0.0] * 383})

    with sessions.begin() as session:
        assert refresh_topic_embeddings(session, embedder) == []
        refreshed = refresh_topic_embeddings(session, other)
        assert refresh_topic_embeddings(session, other) == []
        vectors = {v.name: v.embedding for v in topic_vectors(session)}

    assert len(refreshed) == 2 and wood.id in refreshed
    assert other.calls == [["wood", "birds"]]
    assert vectors["Wood"][0] == 1.0
