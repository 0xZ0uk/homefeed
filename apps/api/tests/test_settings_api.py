from collections.abc import Iterator
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_gateway, get_playback
from homefeed_core import browser_cookies, feeds
from homefeed_core.browser_cookies import BrowserProfile
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import CookieCheck
from homefeed_core.gateway.fake import FakeGateway


class FakePlayback:
    def __init__(self) -> None:
        self.forgotten = 0

    def forget_sponsor_segments(self) -> None:
        self.forgotten += 1


@pytest.fixture
def playback() -> FakePlayback:
    return FakePlayback()


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, playback: FakePlayback
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    monkeypatch.setenv("FEED_SIZE", "25")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-key-0000")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_playback] = lambda: playback
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def patch(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    response = client.patch("/settings", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def stored() -> dict[str, str]:
    with get_session_factory()() as session:
        return {
            key: value for key, value in session.execute(text("SELECT key, value FROM settings"))
        }


def test_get_settings_shows_values_defaults_and_sources(client: TestClient) -> None:
    response = client.get("/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["values"]["feed_size"] == 25
    assert body["values"]["feed_max_topic_share"] == 0.4
    assert body["values"]["feed_refresh_time"] == "06:00"
    assert body["values"]["timezone"] is None
    assert body["values"] == body["defaults"]
    assert body["sources"]["feed_size"] == "env"
    assert body["sources"]["timezone"] == "default"  # no variable of its own
    assert "sponsor" in body["sponsorblock_category_options"]
    assert "system_timezone" in body


def test_patch_sets_and_resets(client: TestClient) -> None:
    body = patch(
        client,
        {
            "set": {
                "feed_size": 10,
                "feed_refresh_time": "07:45",
                "timezone": "Europe/Lisbon",
                "sponsorblock_categories": ["sponsor", "filler"],
                "feed_max_duration_seconds": 3600,
            }
        },
    )

    assert body["values"]["feed_size"] == 10
    assert body["values"]["feed_refresh_time"] == "07:45"
    assert body["values"]["timezone"] == "Europe/Lisbon"
    assert body["values"]["sponsorblock_categories"] == ["sponsor", "filler"]
    assert body["defaults"]["feed_size"] == 25
    assert body["sources"]["feed_size"] == "user"
    assert client.get("/settings").json() == body

    body = patch(client, {"reset": ["feed_size", "timezone"]})

    assert body["values"]["feed_size"] == 25 and body["sources"]["feed_size"] == "env"
    assert body["values"]["timezone"] is None and body["sources"]["timezone"] == "default"
    assert set(stored()) == {
        "feed_refresh_time",
        "sponsorblock_categories",
        "feed_max_duration_seconds",
    }


def test_the_share_of_a_feed_one_topic_may_take_is_a_setting(client: TestClient) -> None:
    body = patch(client, {"set": {"feed_max_topic_share": 0.25}})

    assert body["values"]["feed_max_topic_share"] == 0.25
    assert body["defaults"]["feed_max_topic_share"] == 0.4
    assert body["sources"]["feed_max_topic_share"] == "user"
    assert client.get("/settings").json() == body

    body = patch(client, {"reset": ["feed_max_topic_share"]})

    assert body["values"]["feed_max_topic_share"] == 0.4
    assert body["sources"]["feed_max_topic_share"] == "default"
    assert stored() == {}


def test_null_sets_a_nullable_setting(client: TestClient) -> None:
    patch(client, {"set": {"feed_max_duration_seconds": 600}})

    body = patch(client, {"set": {"feed_max_duration_seconds": None}})

    assert body["values"]["feed_max_duration_seconds"] is None
    assert body["sources"]["feed_max_duration_seconds"] == "user"


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"set": {"feed_size": 0}}, "feed_size"),
        ({"set": {"timezone": "Atlantis/Capital"}}, "Unknown time zone: Atlantis/Capital"),
        ({"set": {"sponsorblock_categories": ["ads"]}}, "Unknown SponsorBlock categories"),
        ({"set": {"feed_exploration_slots": 30}}, "more than the feed size"),
        ({"set": {"feed_max_topic_share": 0.05}}, "feed_max_topic_share"),
        ({"set": {"feed_max_topic_share": 1.5}}, "feed_max_topic_share"),
        ({"set": {"feed_size": 5}, "reset": ["feed_size"]}, "both changed and reset"),
        ({"set": {"ytdlp_cookies_from_browser": "netscape"}}, "can't read cookies from"),
    ],
)
def test_invalid_values_are_422_with_a_string_detail(
    client: TestClient, body: dict[str, Any], detail: str
) -> None:
    response = client.patch("/settings", json=body)

    assert response.status_code == 422
    assert detail in response.json()["detail"]
    assert stored() == {}


@pytest.mark.parametrize(
    "body",
    [
        {"set": {"feed_refresh_time": "noon"}},
        {"set": {"llm_provider": "openai"}},
        {"set": {"theme": "dark"}},
        {"reset": ["theme"]},
    ],
)
def test_malformed_requests_are_422(client: TestClient, body: dict[str, Any]) -> None:
    assert client.patch("/settings", json=body).status_code == 422
    assert stored() == {}


def test_api_key_is_never_returned(client: TestClient) -> None:
    body = client.get("/settings").json()
    assert body["values"]["openrouter_api_key_set"] is True
    assert body["values"]["openrouter_api_key_hint"] == "0000"
    assert body["sources"]["openrouter_api_key"] == "env"

    response = client.patch("/settings", json={"set": {"openrouter_api_key": "sk-or-v1-mine-4321"}})

    assert "sk-or-v1-mine" not in response.text
    assert "sk-or-env-key" not in response.text
    body = response.json()
    assert body["values"]["openrouter_api_key_hint"] == "4321"
    assert body["defaults"]["openrouter_api_key_hint"] == "0000"
    assert "openrouter_api_key" not in body["values"]
    assert "sk-or-v1-mine" not in client.get("/settings").text


def test_api_key_can_be_turned_off_and_reset(client: TestClient) -> None:
    body = patch(client, {"set": {"openrouter_api_key": ""}})
    assert body["values"]["openrouter_api_key_set"] is False
    assert body["values"]["openrouter_api_key_hint"] is None

    body = patch(client, {"reset": ["openrouter_api_key"]})
    assert body["values"]["openrouter_api_key_hint"] == "0000"


def test_changing_sponsorblock_categories_drops_cached_segments(
    client: TestClient, playback: FakePlayback
) -> None:
    patch(client, {"set": {"feed_size": 12}})
    assert playback.forgotten == 0

    patch(client, {"set": {"sponsorblock_categories": ["intro"]}})
    patch(client, {"reset": ["sponsorblock_categories"]})

    assert playback.forgotten == 2


def test_today_feed_is_today_in_the_user_time_zone(client: TestClient) -> None:
    patch(client, {"set": {"timezone": "Pacific/Kiritimati"}})  # UTC+14
    with get_session_factory().begin() as session:
        built = feeds.build_feed(session)

    response = client.get("/feed/today")

    assert built.date == feeds.local_today(tz=ZoneInfo("Pacific/Kiritimati"))
    assert response.status_code == 200, response.text
    assert response.json()["date"] == built.date.isoformat()


def test_youtube_cookies_browser_is_a_setting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    zen = BrowserProfile("Zen (Work)", "firefox:/home/me/.config/zen/abcd.Work")
    monkeypatch.setattr(browser_cookies, "find_browser_profiles", lambda: [zen])
    body = client.get("/settings").json()
    assert body["values"]["ytdlp_cookies_from_browser"] is None
    assert body["cookie_browser_options"] == [{"label": "Zen (Work)", "value": zen.value}]

    body = patch(client, {"set": {"ytdlp_cookies_from_browser": f" {zen.value} "}})

    assert body["values"]["ytdlp_cookies_from_browser"] == zen.value
    assert body["sources"]["ytdlp_cookies_from_browser"] == "user"
    body = patch(client, {"set": {"ytdlp_cookies_from_browser": ""}})
    assert body["values"]["ytdlp_cookies_from_browser"] is None


def test_checking_youtube_cookies(client: TestClient) -> None:
    gateway = FakeGateway()
    gateway.add_cookies("firefox", CookieCheck(youtube_cookies=14, signed_in=True))
    app.dependency_overrides[get_gateway] = lambda: gateway

    response = client.post("/settings/youtube-cookies/check", json={"browser": "firefox"})
    assert response.status_code == 200
    assert response.json() == {"youtube_cookies": 14, "signed_in": True}

    response = client.post("/settings/youtube-cookies/check", json={"browser": "chrome"})
    assert response.status_code == 422
    assert "Couldn't read the browser's cookies" in response.json()["detail"]
    assert stored() == {}
