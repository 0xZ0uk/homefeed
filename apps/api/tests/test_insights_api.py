import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core import feeds
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.insights import week_start

CHANNEL = "UC" + "c" * 22


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    with TestClient(app) as client:
        yield client
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def test_weekly_insights_without_data(client: TestClient) -> None:
    response = client.get("/insights/weekly", params={"weeks": 3})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["good_threshold"] == "B--"
    starts = [week["week_start"] for week in body["weeks"]]
    this_week = week_start(feeds.local_today())
    assert starts == [(this_week - timedelta(weeks=n)).isoformat() for n in (2, 1, 0)]
    assert body["weeks"][-1] == {
        "week_start": this_week.isoformat(),
        "rated_count": 0,
        "good_count": 0,
        "good_tier_rate": None,
        "tier_counts": [{"tier": tier, "count": 0} for tier in "SABCDF"],
        "shown_count": 0,
        "shown_rated_count": 0,
        "rating_rate": None,
        "feed_count": 0,
        "model_feed_count": 0,
        "score_share": None,
    }


def test_weekly_insights_defaults_to_twelve_weeks(client: TestClient) -> None:
    response = client.get("/insights/weekly")

    assert response.status_code == 200
    assert len(response.json()["weeks"]) == 12


@pytest.mark.parametrize("weeks", [0, 105])
def test_weekly_insights_rejects_out_of_range_weeks(client: TestClient, weeks: int) -> None:
    assert client.get("/insights/weekly", params={"weeks": weeks}).status_code == 422


def test_weekly_insights_this_week(client: TestClient) -> None:
    breakdown = {"model": 0.5, "alpha": 0.5, "channel": 0.25, "similarity": 0.0, "topics": {}}
    with get_session_factory().begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES (:id, 'C')"), {"id": CHANNEL})
        feed_id = session.execute(
            text("INSERT INTO feeds (date, model_version) VALUES (:d, '1') RETURNING id"),
            {"d": feeds.local_today().isoformat()},
        ).scalar_one()
        for n in range(2):
            video_id = f"v{n:010d}"
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :c, 'V')"),
                {"id": video_id, "c": CHANNEL},
            )
            session.execute(
                text(
                    """
                    INSERT INTO feed_items (feed_id, video_id, position, source, score,
                                            breakdown, explanation)
                    VALUES (:f, :v, :p, 'subscription', 0.5, :b, '')
                    """
                ),
                {"f": feed_id, "v": video_id, "p": n, "b": json.dumps(breakdown)},
            )
    assert client.put("/ratings/v0000000000", json={"grade": "B--"}).status_code == 200
    assert client.put("/ratings/x0000000000", json={"grade": "C++"}).status_code == 200

    week = client.get("/insights/weekly", params={"weeks": 1}).json()["weeks"][0]

    assert (week["rated_count"], week["good_count"], week["good_tier_rate"]) == (2, 1, 0.5)
    assert {t["tier"]: t["count"] for t in week["tier_counts"]}["B"] == 1
    assert (week["shown_count"], week["shown_rated_count"], week["rating_rate"]) == (2, 1, 0.5)
    assert (week["feed_count"], week["model_feed_count"]) == (1, 1)
    assert week["score_share"] == {"model": 0.5, "curation": 0.5, "similarity": 0.0}
