from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.channel_hides import HideKind, hide
from homefeed_core.curation import (
    mute_tag,
    subscribe,
    subscribe_tag,
    unsubscribe,
    update_channel,
    update_tag_subscription,
)
from homefeed_core.db import open_database
from homefeed_core.feedback import set_feedback
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.fake import FakeGateway, make_channel
from homefeed_core.scores import score_value
from homefeed_core.tags import Tag, add_manual_tag, find_tag, remove_video_tag
from homefeed_core.taste import (
    DEFAULT_DAYS,
    MAX_DAYS,
    WELL_RATED_LIMIT,
    DismissalCount,
    PriorCounts,
    RatedChannel,
    Signals,
    TagTaste,
    Taste,
    taste_summary,
)
from homefeed_core.watch_events import WatchEventType, record_watch_event

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
WOOD = make_channel("UC" + "w" * 22, title="Woodworking")
BIRDS = make_channel("UC" + "b" * 22, title="Birds")
SMITH = make_channel("UC" + "s" * 22, title="Smithing", handle="@smith")
LOOM = make_channel("UC" + "l" * 22, title="Loom")


def stamp(at: datetime) -> str:
    return format_timestamp(at)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    gateway = FakeGateway()
    for channel in (WOOD, BIRDS):
        gateway.add_channel(channel)
    with factory.begin() as session:
        for channel in (WOOD, BIRDS):
            subscribe(session, gateway, channel.url or "")
        for channel in (SMITH, LOOM):  # known, not followed
            session.execute(
                text(
                    "INSERT INTO channels (id, title, handle, thumbnail_url) "
                    "VALUES (:id, :title, :handle, :thumbnail)"
                ),
                {
                    "id": channel.id,
                    "title": channel.title,
                    "handle": channel.handle,
                    "thumbnail": "https://example.invalid/" + channel.title,
                },
            )
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def video(session: Session, channel_id: str, n: int) -> str:
    """A stored video of the channel; returns its id."""
    video_id = f"{channel_id[-4:]}{n:07d}"
    session.execute(
        text("INSERT OR IGNORE INTO videos (id, channel_id, title) VALUES (:id, :channel, 'v')"),
        {"id": video_id, "channel": channel_id},
    )
    return video_id


def feed(
    session: Session,
    at: datetime,
    video_ids: list[str],
    *,
    dismissed: dict[str, tuple[datetime, str | None]] | None = None,
) -> None:
    """A feed built at `at` holding the videos; `dismissed` maps some of them to when
    and why they were dismissed."""
    feed_id = session.execute(
        text("INSERT INTO feeds (date, created_at) VALUES (:date, :at) RETURNING id"),
        {"date": at.date().isoformat(), "at": stamp(at)},
    ).scalar_one()
    for position, video_id in enumerate(video_ids):
        when, reason = (dismissed or {}).get(video_id, (None, None))
        session.execute(
            text(
                """
                INSERT INTO feed_items (feed_id, video_id, position, source, score, breakdown,
                                        explanation, dismissed_at, dismiss_reason)
                VALUES (:feed, :video, :position, 'subscription', 0.5, '{}', 'x',
                        :dismissed_at, :reason)
                """
            ),
            {
                "feed": feed_id,
                "video": video_id,
                "position": position,
                "dismissed_at": None if when is None else stamp(when),
                "reason": reason,
            },
        )


def rate(session: Session, video_id: str, score: int, at: datetime = NOW) -> None:
    session.execute(
        text(
            "INSERT INTO ratings (video_id, score, value, rated_at, updated_at) "
            "VALUES (:id, :score, :value, :at, :at)"
        ),
        {"id": video_id, "score": score, "value": score_value(score), "at": stamp(at)},
    )


def play(
    session: Session, video_id: str, at: datetime, event_type: WatchEventType = "play"
) -> None:
    record_watch_event(session, video_id, event_type, 5.0, 600.0, at=stamp(at))


def tag(session: Session, video_id: str, label: str) -> Tag:
    """Carry `label` on the video, creating the tag if need be."""
    added = add_manual_tag(session, video_id, label)
    assert added is not None
    return added


def follow(session: Session, label: str, weight: float) -> None:
    """Subscribe to the tag `label` (which a video must carry already) at `weight`."""
    found = find_tag(session, label)
    assert found is not None
    subscribe_tag(session, found, weight=weight)


def taste(sessions: sessionmaker[Session], **kwargs: int) -> Taste:
    with sessions() as session:
        return taste_summary(session, now=NOW, **kwargs)


def by_slug(result: Taste) -> dict[str, TagTaste]:
    return {t.slug: t for t in result.tags}


def test_the_window_is_thirty_days() -> None:
    assert DEFAULT_DAYS == 30


def test_a_fresh_install_has_nothing_to_say(tmp_path: Path) -> None:
    factory = open_database(tmp_path / "homefeed.sqlite")
    try:
        with factory() as session:
            result = taste_summary(session, now=NOW)
    finally:
        bind = factory.kw["bind"]
        assert isinstance(bind, Engine)
        bind.dispose()

    assert result == Taste(
        days=30,
        total_picks=0,
        tags=[],
        channel_priors=PriorCounts(0, 0, 0, 0),
        unfollowed_channels=[],
        signals=Signals(0, 0, 0, 0, []),
    )


@pytest.mark.parametrize("days", [0, -1, MAX_DAYS + 1])
def test_days_outside_the_range_are_refused(sessions: sessionmaker[Session], days: int) -> None:
    with sessions() as session, pytest.raises(ValueError, match="days must be between"):
        taste_summary(session, days=days, now=NOW)


@pytest.mark.parametrize("days", [1, MAX_DAYS])
def test_days_at_the_edges_are_fine(sessions: sessionmaker[Session], days: int) -> None:
    assert taste(sessions, days=days).days == days


class TestTopics:
    def test_followed_and_muted_tags_are_listed_by_label_with_their_weights(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            for n, label in enumerate(["Rust", "Godot", "News"]):
                tag(session, video(session, WOOD.id, n), label)
            follow(session, "Rust", 0.8)
            follow(session, "Godot", 0.5)
            follow(session, "News", 0.0)
            crypto = tag(session, video(session, WOOD.id, 3), "crypto")
            mute_tag(session, crypto)
            update_tag_subscription(session, crypto.id, weight=-1, hide=True)
            tag(session, video(session, WOOD.id, 4), "Unfollowed")  # carried, not followed

        result = taste(sessions)

        assert [(t.label, t.weight, t.hide) for t in result.tags] == [
            ("crypto", -1.0, True),
            ("Godot", 0.5, False),
            ("News", 0.0, False),
            ("Rust", 0.8, False),
        ]
        assert all(t.picks == 0 and t.rating_count == 0 for t in result.tags)

    def test_picks_are_distinct_videos_in_feeds_built_in_the_window(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            a, b, c, old, untagged = (video(session, WOOD.id, n) for n in range(5))
            for video_id in (a, b, c, old):
                tag(session, video_id, "Godot")
            tag(session, b, "Rust")
            follow(session, "Godot", 0.5)
            follow(session, "Rust", 0.5)
            feed(session, NOW - timedelta(days=31), [old])
            feed(session, NOW - timedelta(days=29), [a, b])
            feed(session, NOW - timedelta(days=2), [a, c, untagged])  # a again: one pick
            feed(session, NOW - timedelta(hours=1), [a])  # a refresh

        result = taste(sessions)
        tags = by_slug(result)

        assert tags["godot"].picks == 3  # a, b, c
        assert tags["rust"].picks == 1  # b
        assert result.total_picks == 4  # a, b, c and the untagged one; not the old one
        assert by_slug(taste(sessions, days=1))["godot"].picks == 1  # only the hour-old feed
        assert taste(sessions, days=1).total_picks == 1
        assert by_slug(taste(sessions, days=40))["godot"].picks == 4

    def test_a_feed_built_at_the_very_start_of_the_window_counts(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            edge, before = video(session, WOOD.id, 0), video(session, WOOD.id, 1)
            for video_id in (edge, before):
                tag(session, video_id, "Godot")
            follow(session, "Godot", 0.5)
            feed(session, NOW - timedelta(days=30), [edge])
            feed(session, NOW - timedelta(days=30, seconds=1), [before])

        result = taste(sessions)

        assert (by_slug(result)["godot"].picks, result.total_picks) == (1, 1)

    def test_a_pick_counts_as_watched_once_played_or_rated(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            played, rated, both, untouched, opened = (video(session, WOOD.id, n) for n in range(5))
            for video_id in (played, rated, both, untouched, opened):
                tag(session, video_id, "Godot")
            follow(session, "Godot", 0.5)
            feed(session, NOW - timedelta(days=3), [played, rated, both, untouched, opened])
            play(session, played, NOW - timedelta(days=2))
            play(session, played, NOW - timedelta(days=1))  # played twice: still one
            rate(session, rated, 6)
            play(session, both, NOW - timedelta(days=2))
            rate(session, both, 8)
            play(session, opened, NOW - timedelta(days=2), "close")  # opened, never played

        godot = by_slug(taste(sessions))["godot"]

        assert (godot.picks, godot.watched_picks) == (5, 3)

    def test_ratings_of_a_topic_are_counted_and_averaged_over_all_time(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            videos = [video(session, WOOD.id, n) for n in range(4)]
            for video_id in videos:
                tag(session, video_id, "Godot")
            tag(session, videos[0], "Rust")
            follow(session, "Godot", 0.5)
            follow(session, "Rust", 0.5)
            # Two rated long ago and never picked, one picked lately, one not rated.
            rate(session, videos[0], 9, NOW - timedelta(days=200))
            rate(session, videos[1], 8, NOW - timedelta(days=100))
            rate(session, videos[2], 4, NOW - timedelta(days=1))
            feed(session, NOW - timedelta(days=1), [videos[2]])

        tags = by_slug(taste(sessions))

        assert (tags["godot"].rating_count, tags["godot"].average_score) == (3, 7.0)
        assert (tags["rust"].rating_count, tags["rust"].average_score) == (1, 9.0)
        assert tags["godot"].picks == 1

    def test_a_topic_nobody_rated_has_no_average(self, sessions: sessionmaker[Session]) -> None:
        with sessions.begin() as session:
            tag(session, video(session, WOOD.id, 0), "Godot")
            follow(session, "Godot", 0.5)

        godot = by_slug(taste(sessions))["godot"]

        assert (godot.rating_count, godot.average_score) == (0, None)

    def test_a_removed_tag_link_counts_for_nothing(self, sessions: sessionmaker[Session]) -> None:
        with sessions.begin() as session:
            kept, removed = video(session, WOOD.id, 0), video(session, WOOD.id, 1)
            tag(session, kept, "Godot")
            tag(session, removed, "Godot")
            follow(session, "Godot", 0.5)
            feed(session, NOW - timedelta(days=1), [kept, removed])
            rate(session, removed, 2)
            remove_video_tag(session, removed, "godot")

        godot = by_slug(taste(sessions))["godot"]

        assert (godot.picks, godot.rating_count) == (1, 0)

    def test_muted_tags_show_how_often_they_still_get_picked(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            first, second = video(session, WOOD.id, 0), video(session, WOOD.id, 1)
            crypto = tag(session, first, "Crypto")
            tag(session, second, "Crypto")
            mute_tag(session, crypto)
            feed(session, NOW - timedelta(days=1), [first, second])

        crypto = by_slug(taste(sessions))["crypto"]

        assert (crypto.weight, crypto.picks) == (-0.5, 2)


class TestChannels:
    def test_subscribed_channels_are_counted_by_preference(
        self, sessions: sessionmaker[Session]
    ) -> None:
        gateway = FakeGateway()
        extra = [make_channel("UC" + c * 22, title=c) for c in "xyz"]
        for channel in extra:
            gateway.add_channel(channel)
        with sessions.begin() as session:
            for channel in extra:
                subscribe(session, gateway, channel.url or "")
            update_channel(session, WOOD.id, prior="love")
            update_channel(session, extra[0].id, prior="love")
            update_channel(session, extra[1].id, prior="like")
            update_channel(session, extra[2].id, prior="skeptical", muted=True)  # still counted
            unsubscribe(session, BIRDS.id)  # no longer a subscription

        assert taste(sessions).channel_priors == PriorCounts(love=2, like=1, neutral=0, skeptical=1)

    def test_a_channel_rated_well_but_not_followed_is_listed(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            for n, score in enumerate([8, 7, 3]):  # average 6: not well rated
                rate(session, video(session, LOOM.id, n), score)
            for n, score in enumerate([9, 6]):  # average 7.5
                rate(session, video(session, SMITH.id, n), score)

        assert taste(sessions).unfollowed_channels == [
            RatedChannel(SMITH.id, "Smithing", "@smith", "https://example.invalid/Smithing", 2, 7.5)
        ]

    def test_the_bar_is_an_average_of_seven_from_two_ratings(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            rate(session, video(session, SMITH.id, 0), 10)  # one rating, however high
            for n, score in enumerate([7, 7]):  # exactly 7.0
                rate(session, video(session, LOOM.id, n), score)

        assert [c.channel_id for c in taste(sessions).unfollowed_channels] == [LOOM.id]

    def test_followed_channels_are_left_out(self, sessions: sessionmaker[Session]) -> None:
        with sessions.begin() as session:
            for n in range(3):
                rate(session, video(session, WOOD.id, n), 10)

        assert taste(sessions).unfollowed_channels == []

    @pytest.mark.parametrize("kind", ["dismissed", "blocked"])
    def test_a_channel_hidden_from_discover_is_left_out(
        self, sessions: sessionmaker[Session], kind: HideKind
    ) -> None:
        with sessions.begin() as session:
            for n in range(2):
                rate(session, video(session, SMITH.id, n), 9)
            hide(session, SMITH.id, kind)

        assert taste(sessions).unfollowed_channels == []

    def test_ratings_of_videos_without_a_stored_channel_belong_to_no_channel(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            rate(session, "unknown_vid", 10)
            rate(session, "unknown_two", 10)

        assert taste(sessions).unfollowed_channels == []

    def test_the_best_channel_comes_first_then_the_one_with_more_ratings(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            for n, score in enumerate([8, 8]):
                rate(session, video(session, LOOM.id, n), score)
            for n, score in enumerate([8, 8, 8]):
                rate(session, video(session, SMITH.id, n), score)
            third = make_channel("UC" + "t" * 22, title="Tinsmith")
            session.execute(
                text("INSERT INTO channels (id, title) VALUES (:id, :title)"),
                {"id": third.id, "title": third.title},
            )
            for n, score in enumerate([9, 10]):
                rate(session, video(session, third.id, n), score)

        result = taste(sessions).unfollowed_channels

        assert [(c.title, c.average_score, c.rating_count) for c in result] == [
            ("Tinsmith", 9.5, 2),
            ("Smithing", 8.0, 3),
            ("Loom", 8.0, 2),
        ]

    def test_only_the_best_few_are_listed(self, sessions: sessionmaker[Session]) -> None:
        with sessions.begin() as session:
            for c in range(WELL_RATED_LIMIT + 3):
                channel_id = f"UC{c:022d}"
                session.execute(
                    text("INSERT INTO channels (id, title) VALUES (:id, :title)"),
                    {"id": channel_id, "title": f"Channel {c:02d}"},
                )
                for n in range(2):
                    rate(session, video(session, channel_id, n), 7 + c % 3)

        result = taste(sessions).unfollowed_channels

        assert len(result) == WELL_RATED_LIMIT
        assert [c.average_score for c in result] == sorted(
            (c.average_score for c in result), reverse=True
        )


class TestSignals:
    def test_ratings_and_the_videos_watched(self, sessions: sessionmaker[Session]) -> None:
        with sessions.begin() as session:
            played, rated, both = (video(session, WOOD.id, n) for n in range(3))
            play(session, played, NOW - timedelta(days=40))  # all time, not the window
            play(session, both, NOW - timedelta(days=2))
            play(session, both, NOW - timedelta(days=1))
            rate(session, rated, 5)
            rate(session, both, 9)
            play(session, video(session, WOOD.id, 3), NOW, "pause")  # not a watch
            rate(session, "unknown_vid", 8)  # not stored, still rated and watched

        signals = taste(sessions).signals

        assert (signals.ratings, signals.watched) == (3, 4)

    def test_more_and_less_like_this_are_counted(self, sessions: sessionmaker[Session]) -> None:
        with sessions.begin() as session:
            for n in range(5):
                set_feedback(session, video(session, WOOD.id, n), 1 if n < 3 else -1)

        signals = taste(sessions).signals

        assert (signals.more_like_this, signals.less_like_this) == (3, 2)

    def test_dismissals_are_counted_by_reason_over_the_window(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            v = [video(session, WOOD.id, n) for n in range(8)]
            feed(
                session,
                NOW - timedelta(days=5),
                v,
                dismissed={
                    v[0]: (NOW - timedelta(days=4), "Not interested"),
                    v[1]: (NOW - timedelta(days=3), "Not interested"),
                    v[2]: (NOW - timedelta(days=3), "Clickbait"),
                    v[3]: (NOW - timedelta(days=2), None),
                    v[4]: (NOW - timedelta(days=2), "Too long"),
                    v[5]: (NOW - timedelta(days=45), "Too long"),  # before the window
                },
            )  # v[6], v[7]: not dismissed

        assert taste(sessions).signals.dismissals == [
            DismissalCount("Not interested", 2),
            DismissalCount("Clickbait", 1),
            DismissalCount("Too long", 1),
            DismissalCount(None, 1),
        ]
        assert taste(sessions, days=1).signals.dismissals == []
        assert [d.count for d in taste(sessions, days=60).signals.dismissals] == [2, 2, 1, 1]

    def test_a_dismissal_at_the_very_start_of_the_window_counts(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            edge, before = video(session, WOOD.id, 0), video(session, WOOD.id, 1)
            feed(
                session,
                NOW - timedelta(days=40),
                [edge, before],
                dismissed={
                    edge: (NOW - timedelta(days=30), "Clickbait"),
                    before: (NOW - timedelta(days=30, seconds=1), "Clickbait"),
                },
            )

        assert taste(sessions).signals.dismissals == [DismissalCount("Clickbait", 1)]

    def test_a_video_dismissed_from_two_feeds_counts_once_per_reason(
        self, sessions: sessionmaker[Session]
    ) -> None:
        with sessions.begin() as session:
            v = video(session, WOOD.id, 0)
            for days in (3, 2):
                feed(
                    session,
                    NOW - timedelta(days=days),
                    [v],
                    dismissed={v: (NOW - timedelta(days=1), "Clickbait")},
                )

        assert taste(sessions).signals.dismissals == [DismissalCount("Clickbait", 1)]
