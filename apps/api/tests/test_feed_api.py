import random
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_feed_poll, get_gateway
from homefeed_core import feeds
from homefeed_core.candidates import RELATED, SUBSCRIPTION, record
from homefeed_core.config import get_settings
from homefeed_core.curation import subscribe_tag
from homefeed_core.db import get_session_factory
from homefeed_core.feedback import MORE, set_feedback
from homefeed_core.gateway.fake import FakeGateway
from homefeed_core.llm_tags import TAG_PROMPT_VERSION, LLMTags, store_tags
from homefeed_core.ratings import set_rating
from homefeed_core.tags import ProposedTag, resolve_tag, set_llm_tags
from homefeed_core.watch_events import record_watch_event

WOOD = "UC" + "w" * 22
BIRDS = "UC" + "b" * 22
YESTERDAY = feeds.local_today() - timedelta(days=1)


class PollRecorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def __call__(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


@pytest.fixture
def poll() -> PollRecorder:
    return PollRecorder()


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poll: PollRecorder
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    # A purely score-ordered feed; test_refresh_with_exploration_slots turns them on.
    monkeypatch.setenv("FEED_EXPLORATION_SLOTS", "0")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_gateway] = FakeGateway
    app.dependency_overrides[get_feed_poll] = lambda: poll
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def seed() -> None:
    """Two subscribed channels with two recent uploads each; one has no duration (RSS)."""
    now = datetime.now(UTC)
    with get_session_factory().begin() as session:
        for channel_id, title, prior in [(WOOD, "Woodworking", "love"), (BIRDS, "Birds", None)]:
            session.execute(
                text("INSERT INTO channels (id, title, handle) VALUES (:id, :title, NULL)"),
                {"id": channel_id, "title": title},
            )
            session.execute(
                text("INSERT INTO channel_prefs (channel_id, prior) VALUES (:id, :prior)"),
                {"id": channel_id, "prior": prior or "neutral"},
            )
            for n in range(2):
                video_id = f"{channel_id[2]}{n:010d}"
                session.execute(
                    text(
                        """
                        INSERT INTO videos (id, channel_id, title, published_at,
                                            duration_seconds, view_count, thumbnail_url)
                        VALUES (:id, :channel, :title, :published, :duration, :views, :thumb)
                        """
                    ),
                    {
                        "id": video_id,
                        "channel": channel_id,
                        "title": f"{title} {n}",
                        "published": (now - timedelta(hours=n + 1)).isoformat(),
                        "duration": None if n else 600,
                        "views": None if n else 1234,
                        "thumb": None if n else f"https://example.invalid/{video_id}.jpg",
                    },
                )
                record(session, [video_id], source=SUBSCRIPTION, source_detail=channel_id)


def build(feed_date: date) -> feeds.Feed:
    with get_session_factory().begin() as session:
        return feeds.build_feed(session, feed_date=feed_date, rng=random.Random(0))


def test_today_is_404_before_any_feed(client: TestClient) -> None:
    response = client.get("/feed/today")

    assert response.status_code == 404
    assert response.json() == {"detail": f"No feed for {feeds.local_today().isoformat()}"}


def test_feeds_is_empty_before_any_feed(client: TestClient) -> None:
    response = client.get("/feeds")

    assert response.status_code == 200
    assert response.json() == []


def test_refresh_polls_then_builds_todays_feed(client: TestClient, poll: PollRecorder) -> None:
    seed()

    response = client.post("/feed/refresh")

    assert response.status_code == 200, response.text
    body = response.json()
    assert poll.calls == 1
    assert body["date"] == feeds.local_today().isoformat()
    assert body["model_version"] is None
    assert [item["position"] for item in body["items"]] == [0, 1, 2, 3]
    first = body["items"][0]
    assert first["channel_id"] == WOOD  # the loved channel ranks first
    assert first == {
        "id": first["id"],
        "position": 0,
        "video_id": first["video_id"],
        "title": first["title"],
        "description": None,
        "duration_seconds": first["duration_seconds"],
        "published_at": first["published_at"],
        "thumbnail_url": first["thumbnail_url"],
        "view_count": first["view_count"],
        "channel_id": WOOD,
        "channel_title": "Woodworking",
        "channel_handle": None,
        "channel_thumbnail_url": None,
        "source": "subscription",
        "source_detail": WOOD,
        "score": first["score"],
        "breakdown": {
            "model": 0.0,
            "alpha": 0.0,
            "channel": first["breakdown"]["channel"],
            "similarity": 0.0,
            "tags": {},
            "final": first["score"],
            "similarity_features": None,
        },
        "explanation": "New from your subscriptions · channel you love",
        "is_pinned": False,
        "is_exploration": False,
        "selection_probability": None,
        "dismissed_at": None,
        "dismiss_reason": None,
        "watched": False,
        "rating": None,
        "watched_fraction": None,
        "feedback": None,
        "channel_subscribed": True,
        "tags": [],
        "llm": None,
    }
    durations = {item["video_id"]: item["duration_seconds"] for item in body["items"]}
    assert durations["w0000000000"] == 600
    assert durations["w0000000001"] is None  # RSS-only videos have no duration


def test_refresh_with_exploration_slots(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEED_EXPLORATION_SLOTS", "1")
    get_settings.cache_clear()
    seed()

    response = client.post("/feed/refresh")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    explored = [item for item in items if item["is_exploration"]]
    assert len(explored) == 1
    assert items[0] == explored[0]  # exploration comes before the top-scored items
    assert 0.0 < explored[0]["selection_probability"] <= 1.0
    assert explored[0]["explanation"].startswith("Exploring: new channel")
    assert all(item["selection_probability"] is None for item in items[1:])


def test_refresh_survives_a_failing_poll(client: TestClient, poll: PollRecorder) -> None:
    seed()
    poll.error = RuntimeError("network down")

    response = client.post("/feed/refresh")

    assert response.status_code == 200
    assert poll.calls == 1
    assert len(response.json()["items"]) == 4


def test_refresh_with_no_candidates_stores_an_empty_feed(client: TestClient) -> None:
    response = client.post("/feed/refresh")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert client.get("/feed/today").json()["items"] == []


def test_today_returns_the_latest_refresh(client: TestClient) -> None:
    seed()
    first = client.post("/feed/refresh").json()
    second = client.post("/feed/refresh").json()

    response = client.get("/feed/today")

    assert response.status_code == 200
    assert second["id"] != first["id"]
    assert response.json() == second


def test_feed_by_date(client: TestClient) -> None:
    seed()
    past = build(YESTERDAY)

    response = client.get(f"/feed/{YESTERDAY.isoformat()}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == past.id
    assert body["date"] == YESTERDAY.isoformat()
    assert [item["video_id"] for item in body["items"]] == [i.video_id for i in past.items]


def test_feed_by_date_is_404_without_a_feed(client: TestClient) -> None:
    response = client.get("/feed/2020-01-01")

    assert response.status_code == 404
    assert response.json() == {"detail": "No feed for 2020-01-01"}


def test_feed_by_date_rejects_a_bad_date(client: TestClient) -> None:
    assert client.get("/feed/yesterday").status_code == 422
    assert client.get("/feed/2026-13-01").status_code == 422


def test_feeds_lists_the_latest_feed_per_date_newest_first(client: TestClient) -> None:
    seed()
    build(YESTERDAY)
    client.post("/feed/refresh")
    latest = client.post("/feed/refresh").json()

    response = client.get("/feeds")

    assert response.status_code == 200
    body = response.json()
    assert [(f["date"], f["item_count"]) for f in body] == [
        (feeds.local_today().isoformat(), 4),
        (YESTERDAY.isoformat(), 4),
    ]
    assert body[0]["id"] == latest["id"]
    assert set(body[0]) == {"id", "date", "created_at", "model_version", "item_count"}


def test_feeds_limit(client: TestClient) -> None:
    build(YESTERDAY)
    build(YESTERDAY - timedelta(days=1))

    body = client.get("/feeds", params={"limit": 1}).json()

    assert [f["date"] for f in body] == [YESTERDAY.isoformat()]
    assert client.get("/feeds", params={"limit": 0}).status_code == 422


def test_dismiss_sets_dismissed_at_and_reason(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][1]

    response = client.post(f"/feed-items/{item['id']}/dismiss", json={"reason": "Not interested"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dismissed_at"] is not None
    assert body["dismiss_reason"] == "Not interested"
    assert body == {
        **item,
        "dismissed_at": body["dismissed_at"],
        "dismiss_reason": "Not interested",
    }
    today = client.get("/feed/today").json()["items"]
    assert [i["dismissed_at"] is not None for i in today] == [False, True, False, False]


def test_dismiss_without_a_reason(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]

    no_body = client.post(f"/feed-items/{item['id']}/dismiss")
    empty = client.post(f"/feed-items/{item['id']}/dismiss", json={})

    assert no_body.status_code == empty.status_code == 200
    assert no_body.json()["dismissed_at"] is not None
    assert no_body.json()["dismiss_reason"] is None
    assert empty.json() == no_body.json()


def test_dismissed_videos_are_left_out_of_later_feeds(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]
    client.post(f"/feed-items/{item['id']}/dismiss", json={"reason": "Seen it elsewhere"})

    refreshed = client.post("/feed/refresh").json()

    assert item["video_id"] not in {i["video_id"] for i in refreshed["items"]}
    assert len(refreshed["items"]) == 3


def test_dismiss_is_404_for_a_missing_item(client: TestClient) -> None:
    response = client.post("/feed-items/999/dismiss", json={"reason": "x"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Feed item not found"}


def test_dismiss_rejects_bad_input(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]

    too_long = client.post(f"/feed-items/{item['id']}/dismiss", json={"reason": "x" * 201})

    assert too_long.status_code == 422
    assert client.post("/feed-items/0/dismiss").status_code == 422
    assert client.post("/feed-items/abc/dismiss").status_code == 422
    assert client.get("/feed/today").json()["items"][0]["dismissed_at"] is None


def test_undismiss_takes_a_dismissal_back(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][1]
    client.post(f"/feed-items/{item['id']}/dismiss", json={"reason": "Clickbait"})

    response = client.delete(f"/feed-items/{item['id']}/dismiss")

    assert response.status_code == 200, response.text
    assert response.json() == item
    today = client.get("/feed/today").json()["items"]
    assert [i["dismissed_at"] for i in today] == [None] * 4
    assert [i["dismiss_reason"] for i in today] == [None] * 4


def test_undismissed_videos_come_back_in_later_feeds(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]
    client.post(f"/feed-items/{item['id']}/dismiss")
    assert len(client.post("/feed/refresh").json()["items"]) == 3

    client.delete(f"/feed-items/{item['id']}/dismiss")

    refreshed = client.post("/feed/refresh").json()
    assert item["video_id"] in {i["video_id"] for i in refreshed["items"]}


def test_undismiss_of_an_item_that_is_not_dismissed_changes_nothing(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]

    response = client.delete(f"/feed-items/{item['id']}/dismiss")

    assert response.status_code == 200
    assert response.json() == item


def test_undismiss_is_404_for_a_missing_item(client: TestClient) -> None:
    response = client.delete("/feed-items/999/dismiss")

    assert response.status_code == 404
    assert response.json() == {"detail": "Feed item not found"}
    assert client.delete("/feed-items/0/dismiss").status_code == 422


def test_items_carry_what_helps_decide(client: TestClient) -> None:
    seed()
    feed = client.post("/feed/refresh").json()
    target = feed["items"][0]["video_id"]
    with get_session_factory().begin() as session:
        set_rating(session, target, 7)
        set_feedback(session, target, MORE)
        record_watch_event(session, target, "play", 0.0, 600.0)
        record_watch_event(session, target, "pause", 300.0, 600.0)
        # Four tags: only the three most confident are shown on a card.
        proposals = [("Woodworking", 0.9), ("Hand tools", 0.5), ("Chisels", 0.7), ("Rust", 0.3)]
        set_llm_tags(
            session,
            target,
            [ProposedTag(label, confidence) for label, confidence in proposals],
            prompt_version=TAG_PROMPT_VERSION,
        )
        store_tags(session, target, LLMTags("hobbies", 0.8, 0.65, 0.1), model="stub")

    items = {i["video_id"]: i for i in client.get("/feed/today").json()["items"]}

    item = items[target]
    assert (item["watched"], item["rating"], item["feedback"]) == (True, 7, 1)
    assert item["watched_fraction"] == 0.5
    assert item["channel_subscribed"] is True
    assert item["tags"] == [
        {"slug": "woodworking", "label": "Woodworking"},
        {"slug": "chisels", "label": "Chisels"},
        {"slug": "hand-tools", "label": "Hand tools"},
    ]
    assert item["llm"] == {"depth": 0.8, "clickbait": 0.65, "rage_bait": 0.1}
    other = items[feed["items"][1]["video_id"]]
    assert (other["rating"], other["feedback"], other["watched_fraction"]) == (None, None, None)
    assert (other["tags"], other["llm"]) == ([], None)


def test_items_from_channels_not_subscribed_say_so(client: TestClient) -> None:
    seed()
    outside = "UC" + "o" * 22
    with get_session_factory().begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Outside')"), {"id": outside}
        )
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES ('o0000000000', :id, 'Far')"),
            {"id": outside},
        )
        record(session, ["o0000000000"], source=RELATED, source_detail="w0000000000")

    items = client.post("/feed/refresh").json()["items"]

    assert {i["channel_id"]: i["channel_subscribed"] for i in items} == {
        WOOD: True,
        BIRDS: True,
        outside: False,
    }


def test_more_appends_new_picks_to_the_feed(client: TestClient) -> None:
    seed()
    feed = client.post("/feed/refresh").json()
    with get_session_factory().begin() as session:
        session.execute(
            text(
                "INSERT INTO videos (id, channel_id, title, published_at) "
                "VALUES ('fresh000001', :channel, 'Fresh', :published)"
            ),
            {"channel": WOOD, "published": datetime.now(UTC).isoformat()},
        )
        record(session, ["fresh000001"], source=SUBSCRIPTION, source_detail=WOOD)

    response = client.post(f"/feeds/{feed['id']}/more")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == feed["id"]
    assert [item["position"] for item in body["items"]] == [0, 1, 2, 3, 4]
    assert [item["video_id"] for item in body["items"][:4]] == [
        item["video_id"] for item in feed["items"]
    ]
    assert body["items"][4]["video_id"] == "fresh000001"
    assert client.get("/feed/today").json() == body


def test_more_returns_the_feed_unchanged_when_nothing_is_left(client: TestClient) -> None:
    seed()
    feed = client.post("/feed/refresh").json()

    response = client.post(f"/feeds/{feed['id']}/more")

    assert response.status_code == 200
    assert response.json() == feed


def test_more_is_404_for_a_missing_feed(client: TestClient) -> None:
    response = client.post("/feeds/999/more")

    assert response.status_code == 404
    assert response.json() == {"detail": "No such feed"}
    assert client.post("/feeds/0/more").status_code == 422


def test_discovery_videos_come_from_outside_the_subscriptions(client: TestClient) -> None:
    seed()
    assert client.get("/discover/videos").json() == []
    outside = "UC" + "o" * 22
    with get_session_factory().begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Outside')"), {"id": outside}
        )
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES ('o0000000000', :id, 'Far')"),
            {"id": outside},
        )
        record(session, ["o0000000000"], source=RELATED, source_detail="w0000000000")

    response = client.get("/discover/videos")

    assert response.status_code == 200, response.text
    [item] = response.json()
    assert item["video_id"] == "o0000000000"
    assert (item["channel_title"], item["source"]) == ("Outside", RELATED)
    assert item["explanation"].startswith("Related to")
    assert set(item["breakdown"]) >= {"final", "channel", "similarity"}
    assert (item["channel_subscribed"], item["feedback"], item["tags"], item["llm"]) == (
        False,
        None,
        [],
        None,
    )
    assert client.get("/discover/videos", params={"limit": 0}).status_code == 422


def test_discovery_videos_carry_feedback_tags_and_llm_scores(client: TestClient) -> None:
    seed()
    outside = "UC" + "o" * 22
    with get_session_factory().begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Outside')"), {"id": outside}
        )
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES ('o0000000000', :id, 'Far')"),
            {"id": outside},
        )
        record(session, ["o0000000000"], source=RELATED, source_detail="w0000000000")
        set_feedback(session, "o0000000000", MORE)
        set_llm_tags(
            session, "o0000000000", [ProposedTag("Birds", 0.9)], prompt_version=TAG_PROMPT_VERSION
        )
        store_tags(session, "o0000000000", LLMTags("nature", 0.2, 0.9, 0.0), model="stub")

    [item] = client.get("/discover/videos").json()

    assert item["feedback"] == 1
    assert item["tags"] == [{"slug": "birds", "label": "Birds"}]
    assert item["llm"] == {"depth": 0.2, "clickbait": 0.9, "rage_bait": 0.0}


# Channel ids for the videos of `add_outside`, leaving out `w` and `b`, the seeded channels.
OUTSIDE_LETTERS = "acdefghijklmnopqrstuvxyz"


def add_outside(letter: str, *, tags: list[str] | None = None) -> str:
    """A video on an unsubscribed channel of its own, found as related to a video; its id."""
    channel_id = "UC" + letter * 22
    video_id = f"{letter}0000000000"
    with get_session_factory().begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, :title)"),
            {"id": channel_id, "title": f"Outside {letter}"},
        )
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'Far')"),
            {"id": video_id, "channel": channel_id},
        )
        record(session, [video_id], source=RELATED, source_detail="w0000000000")
        if tags:
            proposals = [ProposedTag(tag, 0.9) for tag in tags]
            set_llm_tags(session, video_id, proposals, prompt_version=TAG_PROMPT_VERSION)
    return video_id


def shown_by_discovery(client: TestClient) -> set[str]:
    return {item["video_id"] for item in client.get("/discover/videos").json()}


def test_wildcards_are_empty_without_candidates_outside(client: TestClient) -> None:
    seed()

    response = client.get("/feeds/wildcards")

    assert response.status_code == 200
    assert response.json() == []


def test_wildcards_leave_out_what_discovery_shows(client: TestClient) -> None:
    seed()
    # Discovery shows ten of these (one per channel); the rest are the wildcards' to draw.
    outside = [add_outside(letter) for letter in OUTSIDE_LETTERS[:13]]
    shown = shown_by_discovery(client)

    response = client.get("/feeds/wildcards", params={"limit": 20})

    assert response.status_code == 200, response.text
    items = response.json()
    assert len(shown) == feeds.DISCOVERY_SIZE
    assert {item["video_id"] for item in items} == set(outside) - shown
    item = items[0]
    assert item["explanation"] == "Wildcard: outside the topics you follow"
    assert item["source"] == RELATED
    assert set(item["breakdown"]) >= {"final", "channel", "similarity"}
    assert (item["channel_subscribed"], item["feedback"], item["llm"]) == (False, None, None)


def test_wildcards_come_from_outside_the_topics_i_follow_and_mute(client: TestClient) -> None:
    seed()
    plain = [add_outside(letter) for letter in OUTSIDE_LETTERS[:11]]
    muted = add_outside(OUTSIDE_LETTERS[11], tags=["Drama"])
    other = add_outside(OUTSIDE_LETTERS[12], tags=["Birds"])
    with get_session_factory().begin() as session:
        drama = resolve_tag(session, "Drama")
        assert drama is not None
        subscribe_tag(session, drama, weight=-0.5)
    # The muted one ranks last, so Discovery doesn't show it: only the rule leaves it out.
    shown = shown_by_discovery(client)
    assert muted not in shown

    items = client.get("/feeds/wildcards", params={"limit": 20}).json()

    drawn = {item["video_id"] for item in items}
    assert muted not in drawn
    assert drawn == (set(plain) | {other}) - shown


def test_wildcards_limit(client: TestClient) -> None:
    seed()
    for letter in OUTSIDE_LETTERS[:15]:  # five beyond what Discovery shows
        add_outside(letter)

    assert len(client.get("/feeds/wildcards").json()) == 3  # three by default
    assert len(client.get("/feeds/wildcards", params={"limit": 5}).json()) == 5
    assert len(client.get("/feeds/wildcards", params={"limit": 1}).json()) == 1
    assert client.get("/feeds/wildcards", params={"limit": 0}).status_code == 422
    assert client.get("/feeds/wildcards", params={"limit": 21}).status_code == 422


def test_wildcards_leave_out_todays_feed(client: TestClient) -> None:
    seed()
    outside = [add_outside(letter) for letter in OUTSIDE_LETTERS[:12]]
    assert len(client.get("/feeds/wildcards").json()) == 2

    feed = client.post("/feed/refresh").json()

    assert set(outside) <= {item["video_id"] for item in feed["items"]}
    assert client.get("/feeds/wildcards").json() == []
