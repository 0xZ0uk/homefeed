from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_gateway
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.feeds import load_curation
from homefeed_core.gateway import ExtractionError, GatewayError, RateLimitedError
from homefeed_core.gateway.fake import FakeGateway, make_channel

WOOD = make_channel(
    "UC" + "w" * 22,
    title="Woodworking",
    handle="@wood",
    thumbnail_url="https://example.invalid/wood.jpg",
)
BIRDS = make_channel("UC" + "b" * 22, title="Birds", handle="@birds")


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(WOOD)
    gateway.add_channel(BIRDS)
    return gateway


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_gateway] = lambda: gateway
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def subscribe(client: TestClient, url: str = "https://www.youtube.com/@wood") -> dict:
    response = client.post("/channels", json={"url": url})
    assert response.status_code == 201, response.text
    return response.json()


def stored(sql: str) -> list[tuple]:
    with get_session_factory()() as session:
        return [tuple(row) for row in session.execute(text(sql))]


def test_subscribe_by_url(client: TestClient, gateway: FakeGateway) -> None:
    body = subscribe(client)

    assert body == {
        "channel_id": WOOD.id,
        "title": "Woodworking",
        "handle": "@wood",
        "url": WOOD.url,
        "thumbnail_url": "https://example.invalid/wood.jpg",
        "prior": "neutral",
        "pinned": False,
        "muted": False,
        "muted_until": None,
        "trial_until": None,
        "subscribed_at": body["subscribed_at"],
        "updated_at": body["updated_at"],
    }
    assert gateway.calls == [("resolve_url", "https://www.youtube.com/@wood")]
    assert stored("SELECT id, title, handle FROM channels") == [(WOOD.id, "Woodworking", "@wood")]
    assert stored("SELECT channel_id, prior, pinned, muted FROM channel_prefs") == [
        (WOOD.id, "neutral", 0, 0)
    ]


def test_subscribe_again_returns_200_and_keeps_prefs(client: TestClient) -> None:
    subscribe(client)
    client.patch(f"/channels/{WOOD.id}", json={"prior": "love"})

    response = client.post("/channels", json={"url": f"https://www.youtube.com/channel/{WOOD.id}"})

    assert response.status_code == 200
    assert response.json()["prior"] == "love"
    assert len(stored("SELECT * FROM channel_prefs")) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com/@wood",
        "not a url at all",
    ],
)
def test_subscribe_rejects_non_channel_urls(client: TestClient, url: str) -> None:
    response = client.post("/channels", json={"url": url})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert stored("SELECT * FROM channels") == []


@pytest.mark.parametrize("body", [{}, {"url": ""}])
def test_subscribe_validates_body(client: TestClient, body: dict) -> None:
    assert client.post("/channels", json=body).status_code == 422


def test_subscribe_unknown_channel_is_404(client: TestClient) -> None:
    response = client.post("/channels", json={"url": "https://www.youtube.com/@nobody"})
    assert response.status_code == 404


@pytest.mark.parametrize("error", [ExtractionError("boom"), RateLimitedError("slow down")])
def test_subscribe_gateway_failure_is_502(
    client: TestClient, gateway: FakeGateway, error: GatewayError
) -> None:
    url = "https://www.youtube.com/@wood"
    gateway.fail("resolve_url", url, error)

    assert client.post("/channels", json={"url": url}).status_code == 502
    assert stored("SELECT * FROM channels") == []


def test_list_channels(client: TestClient) -> None:
    assert client.get("/channels").json() == []
    subscribe(client)
    subscribe(client, "@birds")

    response = client.get("/channels")

    assert response.status_code == 200
    assert [c["title"] for c in response.json()] == ["Birds", "Woodworking"]


def test_update_prior_pin_and_mute(client: TestClient) -> None:
    subscribe(client)

    response = client.patch(
        f"/channels/{WOOD.id}", json={"prior": "skeptical", "pinned": True, "muted": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["prior"], body["pinned"], body["muted"]) == ("skeptical", True, True)
    assert stored("SELECT prior, pinned, muted FROM channel_prefs") == [("skeptical", 1, 1)]


def test_update_leaves_omitted_fields(client: TestClient) -> None:
    subscribe(client)
    client.patch(f"/channels/{WOOD.id}", json={"prior": "like", "pinned": True})

    body = client.patch(f"/channels/{WOOD.id}", json={"pinned": False}).json()

    assert (body["prior"], body["pinned"], body["muted"]) == ("like", False, False)


@pytest.mark.parametrize("body", [{"prior": "hate"}, {"pinned": "maybe"}])
def test_update_rejects_invalid_values(client: TestClient, body: dict) -> None:
    subscribe(client)
    assert client.patch(f"/channels/{WOOD.id}", json=body).status_code == 422


def test_update_unsubscribed_channel_is_404(client: TestClient) -> None:
    assert client.patch(f"/channels/{WOOD.id}", json={"pinned": True}).status_code == 404


@pytest.mark.parametrize("channel_id", ["UCshort", "XX" + "w" * 22, "UC" + "w" * 21 + "!"])
def test_rejects_invalid_channel_ids(client: TestClient, channel_id: str) -> None:
    assert client.patch(f"/channels/{channel_id}", json={}).status_code == 422
    assert client.delete(f"/channels/{channel_id}").status_code == 422


def test_unsubscribe(client: TestClient) -> None:
    subscribe(client)

    response = client.delete(f"/channels/{WOOD.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/channels").json() == []
    assert stored("SELECT id FROM channels") == [(WOOD.id,)]
    assert client.delete(f"/channels/{WOOD.id}").status_code == 404


def test_openapi_lists_priors_as_enum(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert schema["SubscribedChannel"]["properties"]["prior"]["enum"] == [
        "love",
        "like",
        "neutral",
        "skeptical",
    ]


def approximately(timestamp: str, expected: datetime) -> bool:
    """Whether an ISO 8601 UTC timestamp is within a minute of `expected`."""
    parsed = datetime.fromisoformat(timestamp)
    return abs(parsed - expected) < timedelta(minutes=1)


def in_days(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def test_mute_for_days_sets_muted_until_and_comes_back_by_itself(client: TestClient) -> None:
    subscribe(client)

    response = client.patch(f"/channels/{WOOD.id}", json={"mute_days": 30})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["muted"] is False
    assert approximately(body["muted_until"], in_days(30))
    assert [c["muted_until"] for c in client.get("/channels").json()] == [body["muted_until"]]
    # The ranker treats it as muted until then, and the channel list stops reporting a
    # mute that has run out.
    with get_session_factory()() as session:
        assert load_curation(session)[WOOD.id].muted
        assert not load_curation(session, now=in_days(31))[WOOD.id].muted
    with get_session_factory().begin() as session:
        session.execute(text("UPDATE channel_prefs SET muted_until = '2020-01-01T00:00:00.000Z'"))
    assert client.get("/channels").json()[0]["muted_until"] is None
    with get_session_factory()() as session:
        assert not load_curation(session)[WOOD.id].muted


def test_muting_for_good_or_unmuting_replaces_a_mute_for_days(client: TestClient) -> None:
    subscribe(client)

    client.patch(f"/channels/{WOOD.id}", json={"mute_days": 7})
    for_good = client.patch(f"/channels/{WOOD.id}", json={"muted": True}).json()
    client.patch(f"/channels/{WOOD.id}", json={"mute_days": 7})
    unmuted = client.patch(f"/channels/{WOOD.id}", json={"muted": False}).json()

    assert (for_good["muted"], for_good["muted_until"]) == (True, None)
    assert (unmuted["muted"], unmuted["muted_until"]) == (False, None)


@pytest.mark.parametrize(
    "body",
    [
        {"muted": True, "mute_days": 7},
        {"mute_days": 0},
        {"mute_days": 366},
        {"mute_days": "a month"},
    ],
)
def test_mute_for_days_rejects_invalid_requests(client: TestClient, body: dict) -> None:
    subscribe(client)

    assert client.patch(f"/channels/{WOOD.id}", json=body).status_code == 422
    assert stored("SELECT muted, muted_until FROM channel_prefs") == [(0, None)]


def known_channel(client: TestClient, channel_id: str = WOOD.id) -> None:
    """Make the channel known without subscribing, as fetching its page does."""
    assert client.get(f"/channels/{channel_id}").status_code == 200


def test_start_a_trial_for_two_weeks(client: TestClient) -> None:
    known_channel(client)

    response = client.post(f"/channels/{WOOD.id}/trial")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["channel_id"] == WOOD.id
    assert approximately(body["trial_until"], in_days(14))
    assert (body["prior"], body["pinned"], body["muted"]) == ("neutral", False, False)
    assert [c["trial_until"] for c in client.get("/channels").json()] == [body["trial_until"]]


def test_starting_a_trial_again_returns_the_subscription_unchanged(client: TestClient) -> None:
    known_channel(client)
    first = client.post(f"/channels/{WOOD.id}/trial").json()

    again = client.post(f"/channels/{WOOD.id}/trial")

    assert again.status_code == 200
    assert again.json() == first


def test_a_plain_subscription_does_not_become_a_trial(client: TestClient) -> None:
    subscribe(client)

    response = client.post(f"/channels/{WOOD.id}/trial")

    assert response.status_code == 200
    assert response.json()["trial_until"] is None


def test_a_trial_needs_a_known_channel(client: TestClient) -> None:
    assert client.post(f"/channels/{WOOD.id}/trial").status_code == 404
    assert client.post("/channels/UC" + "z" * 21 + "!/trial").status_code == 422
    assert client.get("/channels").json() == []


def test_starting_a_trial_clears_the_hide(client: TestClient) -> None:
    known_channel(client)
    client.put(f"/channels/{WOOD.id}/hide", json={"kind": "blocked"})

    client.post(f"/channels/{WOOD.id}/trial")

    assert client.get("/channel-hides").json() == []


def test_keep_a_trial(client: TestClient) -> None:
    known_channel(client)
    client.post(f"/channels/{WOOD.id}/trial")
    client.patch(f"/channels/{WOOD.id}", json={"prior": "love"})

    response = client.post(f"/channels/{WOOD.id}/trial/keep")

    assert response.status_code == 200, response.text
    assert (response.json()["trial_until"], response.json()["prior"]) == (None, "love")
    assert client.post(f"/channels/{WOOD.id}/trial/keep").status_code == 404  # not on trial


def test_keeping_needs_a_trial(client: TestClient) -> None:
    subscribe(client)

    assert client.post(f"/channels/{WOOD.id}/trial/keep").status_code == 404  # plain
    assert client.post(f"/channels/{BIRDS.id}/trial/keep").status_code == 404  # not subscribed


def test_end_a_trial_unsubscribes_and_records_not_now(client: TestClient) -> None:
    known_channel(client)
    client.post(f"/channels/{WOOD.id}/trial")

    response = client.delete(f"/channels/{WOOD.id}/trial")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/channels").json() == []
    hides = client.get("/channel-hides").json()
    assert [(h["channel_id"], h["kind"]) for h in hides] == [(WOOD.id, "dismissed")]
    assert client.delete(f"/channels/{WOOD.id}/trial").status_code == 404


def test_ending_needs_a_trial(client: TestClient) -> None:
    subscribe(client)

    assert client.delete(f"/channels/{WOOD.id}/trial").status_code == 404
    assert len(client.get("/channels").json()) == 1  # still subscribed
    assert client.get("/channel-hides").json() == []


def test_channel_health_lists_subscribed_channels_by_title(client: TestClient) -> None:
    assert client.get("/channels/health").json() == []
    subscribe(client)
    subscribe(client, "https://www.youtube.com/@birds")

    response = client.get("/channels/health")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "channel_id": channel.id,
            "last_watched_at": None,
            "rating_count": 0,
            "average_score": None,
            "picks": 0,
            "watched_picks": 0,
        }
        for channel in (BIRDS, WOOD)
    ]


def test_channel_health_counts_picks_watching_and_ratings(client: TestClient) -> None:
    subscribe(client)
    with get_session_factory().begin() as session:
        for n in range(3):
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'v')"),
                {"id": f"vvvvvvvvvv{n}", "channel": WOOD.id},
            )
        feed_id = session.execute(
            text("INSERT INTO feeds (date) VALUES ('2026-10-12') RETURNING id")
        ).scalar_one()
        for n in range(3):
            session.execute(
                text(
                    "INSERT INTO feed_items (feed_id, video_id, position, source, score, "
                    "breakdown, explanation) VALUES (:feed, :video, :n, 'subscription', 0.5, "
                    "'{}', 'x')"
                ),
                {"feed": feed_id, "video": f"vvvvvvvvvv{n}", "n": n},
            )
    assert (
        client.post(
            "/watch-events", json={"video_id": "vvvvvvvvvv0", "event_type": "play", "position": 0}
        ).status_code
        == 201
    )
    assert client.put("/ratings/vvvvvvvvvv1", json={"score": 8}).status_code == 200
    assert client.put("/ratings/vvvvvvvvvv0", json={"score": 5}).status_code == 200

    [health] = [h for h in client.get("/channels/health").json() if h["channel_id"] == WOOD.id]

    assert (health["picks"], health["watched_picks"]) == (3, 2)
    assert (health["rating_count"], health["average_score"]) == (2, 6.5)
    assert health["last_watched_at"] is not None


def test_channel_health_window_is_a_query_parameter(client: TestClient) -> None:
    subscribe(client)

    assert client.get("/channels/health", params={"days": 7}).status_code == 200
    assert client.get("/channels/health", params={"days": 0}).status_code == 422
    assert client.get("/channels/health", params={"days": 366}).status_code == 422
