import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.channel_hides import HideKind
from homefeed_core.db import open_database
from homefeed_core.insights import (
    MAX_RECAP_TOPICS,
    DiscoveredChannel,
    DiscoveryRecap,
    channel_status,
    discovery_recap,
)
from homefeed_core.scores import score_value
from homefeed_core.tags import ProposedTag, remove_video_tag, set_llm_tags

# A Thursday. The last week is Oct 9 to 15, the one before it Oct 2 to 8.
TODAY = date(2026, 10, 15)


def utc(day: str, clock: str = "12:00:00.000") -> datetime:
    """`day` (YYYY-MM-DD) at `clock`, UTC."""
    return datetime.fromisoformat(f"{day}T{clock}+00:00")


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


def channel_id(letter: str) -> str:
    return "UC" + letter * 22


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def lisbon_is_local(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The process's own time zone is Lisbon's, as when no time zone is set."""
    monkeypatch.setenv("TZ", "Europe/Lisbon")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def add_channel(session: Session, letter: str, title: str | None = None) -> str:
    """A known channel, titled "Channel A" for "a" unless said; returns its id."""
    session.execute(
        text("INSERT OR IGNORE INTO channels (id, title, handle) VALUES (:id, :title, :handle)"),
        {
            "id": channel_id(letter),
            "title": title or f"Channel {letter.upper()}",
            "handle": f"@{letter}",
        },
    )
    return channel_id(letter)


def add_video(session: Session, letter: str, n: int = 0) -> str:
    """A stored video of the channel (made if need be); returns the video's id."""
    channel = add_channel(session, letter)
    video_id = f"{letter}{n:010d}"
    session.execute(
        text("INSERT OR IGNORE INTO videos (id, channel_id, title) VALUES (:id, :channel, 'v')"),
        {"id": video_id, "channel": channel},
    )
    return video_id


def play(session: Session, video_id: str, at: datetime, event_type: str = "play") -> None:
    session.execute(
        text(
            "INSERT INTO watch_events (video_id, event_type, position, duration, at) "
            "VALUES (:video, :type, 5, 600, :at)"
        ),
        {"video": video_id, "type": event_type, "at": stamp(at)},
    )


def watch(session: Session, letter: str, at: datetime, n: int = 0) -> str:
    """Play video `n` of the channel at `at`; returns the video's id."""
    video_id = add_video(session, letter, n)
    play(session, video_id, at)
    return video_id


def rate(session: Session, video_id: str, score: int, at: datetime | None = None) -> None:
    session.execute(
        text(
            "INSERT INTO ratings (video_id, score, value, rated_at, updated_at) "
            "VALUES (:video, :score, :value, :at, :at)"
        ),
        {
            "video": video_id,
            "score": score,
            "value": score_value(score),
            "at": stamp(at or utc("2026-10-14")),
        },
    )


def subscribe(session: Session, letter: str, trial_until: datetime | None = None) -> None:
    session.execute(
        text("INSERT INTO channel_prefs (channel_id, trial_until) VALUES (:id, :until)"),
        {"id": add_channel(session, letter), "until": stamp(trial_until) if trial_until else None},
    )


def hide(session: Session, letter: str, kind: HideKind) -> None:
    session.execute(
        text("INSERT INTO channel_hides (channel_id, kind) VALUES (:id, :kind)"),
        {"id": add_channel(session, letter), "kind": kind},
    )


def recap(sessions: sessionmaker[Session], days: int = 7) -> DiscoveryRecap:
    with sessions() as session:
        return discovery_recap(session, today=TODAY, days=days, tz=UTC)


def found(result: DiscoveryRecap) -> dict[str, DiscoveredChannel]:
    """The new channels by the letter their id is made of."""
    return {channel.channel_id[2]: channel for channel in result.channels}


def test_an_empty_database_has_nothing_new(sessions: sessionmaker[Session]) -> None:
    result = recap(sessions)

    assert result.days == 7
    assert (result.current.start, result.current.end) == (date(2026, 10, 9), TODAY)
    assert (result.previous.start, result.previous.end) == (date(2026, 10, 2), date(2026, 10, 8))
    for window in (result.current, result.previous):
        assert (window.new_channels, window.kept_channels, window.liked_channels) == (0, 0, 0)
        assert (window.videos_watched, window.new_channel_videos) == (0, 0)
        assert (window.new_channel_share, window.new_topics) == (None, 0)
    assert result.channels == []
    assert result.topics == []


def test_days_sets_the_length_of_both_windows(sessions: sessionmaker[Session]) -> None:
    result = recap(sessions, days=3)

    assert (result.current.start, result.current.end) == (date(2026, 10, 13), TODAY)
    assert (result.previous.start, result.previous.end) == (date(2026, 10, 10), date(2026, 10, 12))


@pytest.mark.parametrize("days", [0, -1, 91])
def test_days_out_of_range_is_refused(sessions: sessionmaker[Session], days: int) -> None:
    with sessions() as session, pytest.raises(ValueError):
        discovery_recap(session, today=TODAY, days=days)


def test_windows_begin_and_end_at_local_midnight(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        watch(session, "a", utc("2026-10-01", "23:59:59.999"))  # before both windows
        watch(session, "b", utc("2026-10-02", "00:00:00.000"))  # the first moment of the earlier
        watch(session, "c", utc("2026-10-08", "23:59:59.999"))  # the last moment of the earlier
        watch(session, "d", utc("2026-10-09", "00:00:00.000"))  # the first moment of the last
        watch(session, "e", utc("2026-10-15", "23:59:59.999"))  # the last moment of the last
        watch(session, "f", utc("2026-10-16", "00:00:00.000"))  # tomorrow

    result = recap(sessions)

    assert set(found(result)) == {"d", "e"}
    assert result.current.new_channels == 2
    assert result.previous.new_channels == 2


def test_the_time_zone_decides_which_day_a_play_falls_on(
    sessions: sessionmaker[Session],
) -> None:
    lisbon = ZoneInfo("Europe/Lisbon")  # UTC+1 until Oct 25
    with sessions.begin() as session:
        watch(session, "a", utc("2026-10-08", "23:30:00.000"))  # Oct 9, 00:30 in Lisbon
        watch(session, "b", utc("2026-10-15", "23:30:00.000"))  # Oct 16, 00:30 in Lisbon

    in_utc = recap(sessions)
    with sessions() as session:
        in_lisbon = discovery_recap(session, today=TODAY, tz=lisbon)

    assert set(found(in_utc)) == {"b"}
    assert in_utc.previous.new_channels == 1
    assert set(found(in_lisbon)) == {"a"}
    assert in_lisbon.previous.new_channels == 0


@pytest.mark.usefixtures("lisbon_is_local")
def test_without_a_time_zone_days_are_the_process_s_own(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        watch(session, "a", utc("2026-10-08", "23:30:00.000"))  # Oct 9, 00:30 in Lisbon
        watch(session, "b", utc("2026-10-15", "23:30:00.000"))  # Oct 16, 00:30 in Lisbon

    with sessions() as session:
        result = discovery_recap(session, today=TODAY)

    assert set(found(result)) == {"a"}
    assert result.previous.new_channels == 0


def test_a_day_that_is_25_hours_long_still_runs_midnight_to_midnight(
    sessions: sessionmaker[Session],
) -> None:
    lisbon = ZoneInfo("Europe/Lisbon")  # the clocks go back on Oct 25: WEST, then WET
    with sessions.begin() as session:
        watch(session, "a", utc("2026-10-24", "22:59:59.999"))  # Oct 24, 23:59 in Lisbon
        watch(session, "b", utc("2026-10-24", "23:00:00.000"))  # Oct 25, 00:00
        watch(session, "c", utc("2026-10-26", "00:00:00.000"))  # Oct 26, 00:00: the next day
        watch(session, "d", utc("2026-10-26", "23:59:59.999"))  # Oct 26, 23:59
        watch(session, "e", utc("2026-10-27", "00:00:00.000"))  # Oct 27, 00:00: tomorrow

    with sessions() as session:
        result = discovery_recap(session, today=date(2026, 10, 26), days=2, tz=lisbon)

    assert (result.current.start, result.current.end) == (date(2026, 10, 25), date(2026, 10, 26))
    assert set(found(result)) == {"b", "c", "d"}
    assert result.previous.new_channels == 1  # a, the day before


def test_a_channel_is_new_when_its_first_play_is_in_the_window(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        # Played before and again this week: not new, though its play is a video watched.
        watch(session, "a", utc("2026-09-20"), 0)
        watch(session, "a", utc("2026-10-12"), 1)
        # First played this week: one video twice, and a second one.
        watch(session, "b", utc("2026-10-10"), 0)
        play(session, "b0000000000", utc("2026-10-11"))
        watch(session, "b", utc("2026-10-13"), 1)
        # First played the week before, and again this week.
        watch(session, "c", utc("2026-10-05"), 0)
        watch(session, "c", utc("2026-10-14"), 1)

    result = recap(sessions)

    assert set(found(result)) == {"b"}
    assert found(result)["b"].videos_watched == 2
    assert result.current.new_channels == 1
    assert result.previous.new_channels == 1
    assert result.current.videos_watched == 4  # a1, b0, b1 and c1
    assert result.previous.videos_watched == 1  # c0


def test_only_plays_of_stored_videos_make_a_channel_new(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        # Opened and closed without a play event; rated without being played.
        opened = add_video(session, "a")
        play(session, opened, utc("2026-10-12"), "pause")
        play(session, opened, utc("2026-10-12"), "close")
        rate(session, add_video(session, "b"), 9)
        # A play of a video that was never stored belongs to no channel.
        play(session, "zzzzzzzzzzz", utc("2026-10-12"))

    result = recap(sessions)

    assert result.channels == []
    assert (result.current.new_channels, result.current.videos_watched) == (0, 0)


def test_the_new_channel_share_counts_distinct_videos(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        watch(session, "a", utc("2026-09-01"), 0)  # an old acquaintance
        watch(session, "a", utc("2026-10-10"), 1)
        play(session, watch(session, "a", utc("2026-10-11"), 2), utc("2026-10-12"))  # twice
        watch(session, "b", utc("2026-10-13"))  # new this week
        watch(session, "c", utc("2026-10-05"), 0)  # new the week before
        watch(session, "c", utc("2026-10-06"), 1)
        watch(session, "d", utc("2026-09-01"), 0)
        watch(session, "d", utc("2026-10-07"), 1)

    result = recap(sessions)

    assert result.current.videos_watched == 3
    assert result.current.new_channel_videos == 1
    assert result.current.new_channel_share == pytest.approx(1 / 3)
    assert result.previous.videos_watched == 3
    assert result.previous.new_channel_videos == 2
    assert result.previous.new_channel_share == pytest.approx(2 / 3)


def test_a_video_played_in_both_windows_counts_in_each(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        video = watch(session, "a", utc("2026-10-08", "23:00:00.000"))
        play(session, video, utc("2026-10-09", "01:00:00.000"))

    result = recap(sessions)

    assert (result.previous.videos_watched, result.current.videos_watched) == (1, 1)
    # The channel was new the week before; this week the video is a repeat.
    assert (result.previous.new_channel_videos, result.current.new_channel_videos) == (1, 0)
    assert result.channels == []


@pytest.mark.parametrize(
    ("subscribed", "trial_until", "hide_kind", "status"),
    [
        (True, None, None, "subscribed"),
        (True, "2026-10-29T00:00:00.000Z", None, "trial"),
        (True, None, "blocked", "subscribed"),  # subscribing clears a hide, so it wins
        (False, None, "dismissed", "hidden"),
        (False, None, "blocked", "hidden"),
        (False, None, None, "not_followed"),
    ],
)
def test_channel_status_words_where_a_channel_stands(
    subscribed: bool, trial_until: str | None, hide_kind: HideKind | None, status: str
) -> None:
    assert (
        channel_status(subscribed=subscribed, trial_until=trial_until, hide_kind=hide_kind)
        == status
    )


def test_each_new_channel_has_its_status_as_it_stands(sessions: sessionmaker[Session]) -> None:
    trial_until = utc("2026-10-29")
    with sessions.begin() as session:
        for letter in "abcdef":
            watch(session, letter, utc("2026-10-12"))
        subscribe(session, "a")
        subscribe(session, "b", trial_until)
        hide(session, "c", "dismissed")
        hide(session, "d", "blocked")
        subscribe(session, "e")
        hide(session, "e", "blocked")  # both rows: the subscription wins
        # f: neither

    channels = found(recap(sessions))

    def stands(letter: str) -> tuple[str, str | None, str | None]:
        channel = channels[letter]
        return (channel.status, channel.trial_until, channel.hide_kind)

    assert stands("a") == ("subscribed", None, None)
    assert stands("b") == ("trial", stamp(trial_until), None)
    assert stands("c") == ("hidden", None, "dismissed")
    assert stands("d") == ("hidden", None, "blocked")
    assert stands("e") == ("subscribed", None, None)
    assert stands("f") == ("not_followed", None, None)


def test_a_subscribed_channel_you_had_not_watched_is_new_and_kept(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        subscribe(session, "a")  # from an import, say; its first play is this week
        watch(session, "a", utc("2026-10-11"))
        watch(session, "b", utc("2026-10-11"))

    result = recap(sessions)

    assert result.current.new_channels == 2
    assert result.current.kept_channels == 1


def test_kept_counts_subscriptions_and_trials_in_each_window(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        # This week: one subscribed, one on trial, one hidden, one not followed.
        for letter in "abcd":
            watch(session, letter, utc("2026-10-12"))
        subscribe(session, "a")
        subscribe(session, "b", utc("2026-10-29"))
        hide(session, "c", "dismissed")
        # The week before: one of two kept.
        watch(session, "e", utc("2026-10-05"))
        watch(session, "f", utc("2026-10-06"))
        subscribe(session, "e")

    result = recap(sessions)

    assert (result.current.new_channels, result.current.kept_channels) == (4, 2)
    assert (result.previous.new_channels, result.previous.kept_channels) == (2, 1)


def test_liked_channels_have_a_video_rated_7_or_higher(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rate(session, watch(session, "a", utc("2026-10-10")), 6)  # good, but not top tier
        rate(session, watch(session, "b", utc("2026-10-10")), 7)
        rate(session, watch(session, "c", utc("2026-10-10")), 10)
        watch(session, "d", utc("2026-10-10"))  # not rated
        # A video of the channel rated without being played counts as well.
        watch(session, "e", utc("2026-10-10"), 0)
        rate(session, add_video(session, "e", 1), 9)
        # Tried the week before, rated since: the numbers are as of now.
        rate(session, watch(session, "f", utc("2026-10-05")), 8, utc("2026-10-14"))

    result = recap(sessions)

    assert (result.current.new_channels, result.current.liked_channels) == (5, 3)
    assert (result.previous.new_channels, result.previous.liked_channels) == (1, 1)


def test_follow_ups_are_top_rated_channels_you_do_not_follow(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        for letter, score in [("a", 9), ("b", 9), ("c", 9), ("d", 8), ("e", 7), ("f", 6)]:
            rate(session, watch(session, letter, utc("2026-10-12")), score)
        watch(session, "g", utc("2026-10-12"))  # not rated
        subscribe(session, "a")
        subscribe(session, "b", utc("2026-10-29"))
        hide(session, "c", "blocked")
        hide(session, "d", "dismissed")
        # e and f: not followed

    channels = found(recap(sessions))

    assert {letter for letter, channel in channels.items() if channel.follow_up} == {"c", "d", "e"}


def test_a_new_channel_has_its_ratings_summed_up(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rate(session, watch(session, "a", utc("2026-10-10"), 0), 9)
        rate(session, watch(session, "a", utc("2026-10-11"), 1), 6)
        watch(session, "a", utc("2026-10-12"), 2)  # not rated
        watch(session, "b", utc("2026-10-12"))

    channels = found(recap(sessions))

    rated = channels["a"]
    assert (rated.videos_watched, rated.rating_count) == (3, 2)
    assert (rated.average_score, rated.top_score) == (7.5, 9)
    assert (rated.title, rated.handle, rated.thumbnail_url) == ("Channel A", "@a", None)
    plain = channels["b"]
    assert (plain.videos_watched, plain.rating_count) == (1, 0)
    assert (plain.average_score, plain.top_score) == (None, None)


def test_new_channels_are_listed_best_rated_first(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_channel(session, "e", "alpha")
        rate(session, watch(session, "a", utc("2026-10-10")), 6)
        rate(session, watch(session, "b", utc("2026-10-10")), 9)
        watch(session, "c", utc("2026-10-10"), 0)
        watch(session, "c", utc("2026-10-11"), 1)  # two videos: ahead of the one-video ones
        watch(session, "d", utc("2026-10-10"))
        watch(session, "e", utc("2026-10-10"))
        rate(session, watch(session, "f", utc("2026-10-10")), 6)

    result = recap(sessions)

    # Rated by average score, ties by videos watched, then title; then the unrated.
    assert [channel.channel_id[2] for channel in result.channels] == list("bafced")


def test_a_topic_is_new_when_it_first_appears_in_the_window(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        old = watch(session, "a", utc("2026-09-20"), 0)
        same = watch(session, "a", utc("2026-10-10"), 1)
        fresh = watch(session, "b", utc("2026-10-11"))
        last_week = watch(session, "c", utc("2026-10-05"))
        set_llm_tags(session, old, [ProposedTag("Woodworking", 0.9)], prompt_version=1)
        set_llm_tags(
            session,
            same,
            [ProposedTag("Woodworking", 0.8), ProposedTag("Hand tools", 0.7)],
            prompt_version=1,
        )
        set_llm_tags(
            session,
            fresh,
            [ProposedTag("Welding", 0.9), ProposedTag("Hand tools", 0.5)],
            prompt_version=1,
        )
        set_llm_tags(session, last_week, [ProposedTag("Birds", 0.9)], prompt_version=1)

    result = recap(sessions)

    # Woodworking was seen in September; Birds belongs to the week before.
    assert [(t.slug, t.label, t.videos) for t in result.topics] == [
        ("hand-tools", "Hand tools", 2),
        ("welding", "Welding", 1),
    ]
    assert result.current.new_topics == 2
    assert result.previous.new_topics == 1


def test_a_rating_brings_topics_in_and_the_first_sight_decides(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        # Rated in the window, never played here.
        rated = add_video(session, "a", 0)
        rate(session, rated, 8, utc("2026-10-12"))
        # Rated in the window, but played the week before: first seen then.
        earlier = watch(session, "b", utc("2026-10-05"))
        rate(session, earlier, 8, utc("2026-10-12"))
        # Played in the window, rated long ago: first seen then.
        long_ago = add_video(session, "c", 0)
        rate(session, long_ago, 5, utc("2026-08-01"))
        play(session, long_ago, utc("2026-10-12"))
        for video_id, label in [(rated, "Rated only"), (earlier, "Earlier"), (long_ago, "Old")]:
            set_llm_tags(session, video_id, [ProposedTag(label, 0.9)], prompt_version=1)

    result = recap(sessions)

    assert [t.label for t in result.topics] == ["Rated only"]
    assert result.previous.new_topics == 1


def test_removed_tags_and_unseen_videos_bring_no_topics(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        seen = watch(session, "a", utc("2026-10-11"))
        unseen = add_video(session, "b")
        set_llm_tags(
            session,
            seen,
            [ProposedTag("Kept", 0.9), ProposedTag("Removed", 0.9)],
            prompt_version=1,
        )
        set_llm_tags(session, unseen, [ProposedTag("Candidate", 0.9)], prompt_version=1)
        remove_video_tag(session, seen, "removed")

    result = recap(sessions)

    assert [t.slug for t in result.topics] == ["kept"]
    assert result.current.new_topics == 1


def test_the_topic_list_is_capped_but_counted_in_full(sessions: sessionmaker[Session]) -> None:
    labels = [f"Topic {n:02d}" for n in range(MAX_RECAP_TOPICS + 3)]
    with sessions.begin() as session:
        first = watch(session, "a", utc("2026-10-11"), 0)
        second = watch(session, "a", utc("2026-10-12"), 1)
        set_llm_tags(
            session, first, [ProposedTag(label, 0.9) for label in labels], prompt_version=1
        )
        set_llm_tags(session, second, [ProposedTag(labels[-1], 0.9)], prompt_version=1)

    result = recap(sessions)

    assert result.current.new_topics == MAX_RECAP_TOPICS + 3
    assert len(result.topics) == MAX_RECAP_TOPICS
    # The one on two videos first, then alphabetically.
    assert [t.label for t in result.topics[:3]] == [labels[-1], "Topic 00", "Topic 01"]
    assert result.topics[0].videos == 2


def test_nothing_after_today_is_counted(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        later = watch(session, "a", utc("2026-10-20"))
        rated = add_video(session, "b")
        rate(session, rated, 9, utc("2026-10-20"))
        set_llm_tags(session, later, [ProposedTag("Later", 0.9)], prompt_version=1)
        set_llm_tags(session, rated, [ProposedTag("Rated later", 0.9)], prompt_version=1)

    result = recap(sessions)

    assert result.channels == []
    assert (result.current.videos_watched, result.current.new_topics) == (0, 0)
    assert result.topics == []
