from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_feed_poll
from homefeed_core.candidates import SUBSCRIPTION, record
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.model_features import FEATURE_NAMES, FEATURE_VERSION
from homefeed_core.ranking_models import (
    RidgeModel,
    activate,
    load_active_model,
    record_version,
    save_model,
)

CHANNEL = "UC" + "m" * 22


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FEED_EXPLORATION_SLOTS", "0")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_feed_poll] = lambda: None
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def constant_model(value: float) -> RidgeModel:
    """A model predicting `value` for every video, so versions are told apart."""
    zeros = np.zeros(len(FEATURE_NAMES))
    return RidgeModel(mean=zeros, scale=np.ones(len(FEATURE_NAMES)), coef=zeros, intercept=value)


def add_version(
    value: float, *, spearman: float | None = 0.5, mae: float = 0.3, active: bool = False
) -> int:
    """Store a trained version (with its file) that predicts `value`; returns its id."""
    path = save_model(constant_model(value))
    with get_session_factory().begin() as session:
        version = record_version(
            session,
            path=path,
            kind="ridge",
            spearman=spearman,
            mae=mae,
            metrics={"n_train": 40, "n_holdout": 10},
            now=datetime(2026, 10, 1, 3, 0, tzinfo=UTC),
        )
        if active:
            activate(session, version.id, now=datetime(2026, 10, 1, 3, 1, tzinfo=UTC))
    return version.id


def seed_candidate() -> None:
    with get_session_factory().begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Models')"), {"id": CHANNEL}
        )
        session.execute(
            text("INSERT INTO channel_prefs (channel_id) VALUES (:id)"), {"id": CHANNEL}
        )
        session.execute(
            text(
                """
                INSERT INTO videos (id, channel_id, title, published_at, duration_seconds)
                VALUES ('mmmmmmmmmm0', :channel, 'A video', :published, 600)
                """
            ),
            {"channel": CHANNEL, "published": datetime.now(UTC).isoformat()},
        )
        record(session, ["mmmmmmmmmm0"], source=SUBSCRIPTION, source_detail=CHANNEL)


def test_models_is_empty_before_any_training(client: TestClient) -> None:
    response = client.get("/models")

    assert response.status_code == 200
    assert response.json() == []


def test_list_models_newest_first_with_metrics(client: TestClient) -> None:
    older = add_version(0.1, spearman=0.42, mae=0.31, active=True)
    newer = add_version(0.2, spearman=None, mae=0.4)

    response = client.get("/models")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [v["id"] for v in body] == [newer, older]
    assert body[1] == {
        "id": older,
        "kind": "ridge",
        "feature_version": FEATURE_VERSION,
        "compatible": True,
        "spearman": 0.42,
        "mae": 0.31,
        "metrics": {"n_train": 40, "n_holdout": 10},
        "created_at": "2026-10-01T03:00:00.000Z",
        "active": True,
        "activated_at": "2026-10-01T03:01:00.000Z",
    }
    assert body[0]["spearman"] is None
    assert body[0]["active"] is False
    assert body[0]["activated_at"] is None


def test_activate_switches_the_active_version(client: TestClient) -> None:
    older = add_version(0.1)
    newer = add_version(0.2, active=True)

    response = client.post(f"/models/{older}/activate")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == older
    assert response.json()["active"] is True
    assert response.json()["activated_at"] is not None
    actives = [v["id"] for v in client.get("/models").json() if v["active"]]
    assert actives == [older]
    assert newer not in actives


def test_activate_unknown_version_is_404(client: TestClient) -> None:
    response = client.post("/models/999/activate")

    assert response.status_code == 404
    assert response.json() == {"detail": "Model version not found"}


def test_activate_rejects_versions_trained_with_other_features(client: TestClient) -> None:
    active = add_version(0.1, active=True)
    stale = add_version(0.2)
    with get_session_factory().begin() as session:
        session.execute(
            text("UPDATE model_versions SET feature_version = 0 WHERE id = :id"), {"id": stale}
        )
    assert client.get("/models").json()[0]["compatible"] is False

    response = client.post(f"/models/{stale}/activate")

    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    actives = [v["id"] for v in client.get("/models").json() if v["active"]]
    assert actives == [active]


def test_rollback_changes_the_model_used_for_the_next_feed(client: TestClient) -> None:
    older = add_version(-0.5)
    newer = add_version(0.5, active=True)

    def used_model() -> tuple[int, float]:
        # The seam the feed build loads its model through.
        with get_session_factory()() as session:
            active = load_active_model(session)
        assert active is not None
        (prediction,) = active.model.predict_matrix(np.zeros((1, len(FEATURE_NAMES)))).tolist()
        return active.version.id, prediction

    assert used_model() == (newer, 0.5)

    response = client.post(f"/models/{older}/activate")
    assert response.status_code == 200, response.text

    assert used_model() == (older, -0.5)


def test_rollback_is_recorded_on_the_next_feed(client: TestClient) -> None:
    seed_candidate()
    older = add_version(-0.5)
    newer = add_version(0.5, active=True)

    before = client.post("/feed/refresh")
    assert before.status_code == 200, before.text
    if before.json()["model_version"] is None:
        pytest.skip("feeds don't rank with the active model yet (model inference, #25)")
    assert before.json()["model_version"] == str(newer)

    assert client.post(f"/models/{older}/activate").status_code == 200
    after = client.post("/feed/refresh")

    assert after.status_code == 200, after.text
    assert after.json()["model_version"] == str(older)
