"""Trained ranking models: the predictors, their files and the `model_versions` registry.

A model predicts a rating value (in [-1, 1]) from `ModelInput`s (see
homefeed_core.model_features). Two kinds exist: `LightGBMModel`, used once there are
enough explicit ratings, and `RidgeModel`, the fallback while labels are few. The
trainer (homefeed_core.trainer) fits them; everything else loads and predicts:

    with sessions() as session:
        active = load_active_model(session)  # None: no usable model, rank rules-only
    if active is not None:
        scores = active.model.predict([ModelInput.for_candidate(...), ...])
        feed_model_version = str(active.version.id)

The feed build hands `ranker_model(active.model, now=now)` to the ranker.

Files are JSON (LightGBM's text model or the ridge coefficients, plus the feature names
and `FEATURE_VERSION`) in `DATA_DIR/ranking_models/`, named in `model_versions.path`
relative to `DATA_DIR`. A model trained with other features than the current
`FEATURE_VERSION` refuses to load (`IncompatibleModelError`).

At most one version is active. `activate` switches it (the trainer's promotion, and
rollback to an earlier version); `prune_versions` drops all but the newest
`KEEP_VERSIONS` (never the active one).
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import lightgbm as lgb
import numpy as np
from numpy.typing import NDArray
from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.config import get_settings
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.model_features import FEATURE_NAMES, FEATURE_VERSION, ModelInput, feature_matrix
from homefeed_core.ranker import Model, ModelCandidate

logger = logging.getLogger(__name__)

ModelKind = Literal["lightgbm", "ridge"]

# Directory under DATA_DIR holding the model files.
MODELS_DIR = "ranking_models"
# Versions kept for rollback (the active one is kept regardless).
KEEP_VERSIONS = 10
# Version of the file layout written by `save_model`.
_FILE_FORMAT = 1


class IncompatibleModelError(Exception):
    """The model file was written for other features or by an unknown format."""


type Matrix = NDArray[np.float64]
type Vector = NDArray[np.float64]


class RankingModel(ABC):
    """Predicts rating values in [-1, 1] from model inputs."""

    kind: ModelKind

    def predict(self, inputs: Sequence[ModelInput]) -> list[float]:
        """Predicted rating values, one per input, clipped to [-1, 1]."""
        if not inputs:
            return []
        return self.predict_matrix(feature_matrix(inputs)).tolist()

    def predict_matrix(self, features: Matrix) -> Vector:
        """`predict` for a matrix from `feature_matrix`."""
        return np.clip(self._predict(features), -1.0, 1.0)

    @abstractmethod
    def _predict(self, features: Matrix) -> Vector: ...

    @abstractmethod
    def _params(self) -> dict[str, Any]: ...

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": _FILE_FORMAT,
            "kind": self.kind,
            "feature_version": FEATURE_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "params": self._params(),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "RankingModel":
        """Read back `to_dict` output. Raises IncompatibleModelError if it was written
        for other features or in an unknown format."""
        if data.get("format") != _FILE_FORMAT:
            raise IncompatibleModelError(f"Unknown model file format {data.get('format')!r}")
        if (
            data.get("feature_version") != FEATURE_VERSION
            or tuple(data.get("feature_names", ())) != FEATURE_NAMES
        ):
            raise IncompatibleModelError(
                f"Model was trained with feature version {data.get('feature_version')!r}, "
                f"not the current {FEATURE_VERSION}"
            )
        params = data["params"]
        match data.get("kind"):
            case "ridge":
                return RidgeModel(
                    mean=np.array(params["mean"], dtype=np.float64),
                    scale=np.array(params["scale"], dtype=np.float64),
                    coef=np.array(params["coef"], dtype=np.float64),
                    intercept=float(params["intercept"]),
                )
            case "lightgbm":
                return LightGBMModel(lgb.Booster(model_str=params["model"]))
            case kind:
                raise IncompatibleModelError(f"Unknown model kind {kind!r}")


class RidgeModel(RankingModel):
    """Weighted ridge regression on standardized features; unknown values are imputed
    with the training mean (0 after standardizing)."""

    kind: ModelKind = "ridge"

    def __init__(self, *, mean: Vector, scale: Vector, coef: Vector, intercept: float) -> None:
        self.mean, self.scale, self.coef, self.intercept = mean, scale, coef, intercept

    @classmethod
    def fit(cls, features: Matrix, labels: Vector, weights: Vector, *, l2: float) -> "RidgeModel":
        """Minimize `sum(w * (y - x.b - c) ** 2) + l2 * |b| ** 2` (intercept unpenalized)."""
        with np.errstate(all="ignore"):
            known = ~np.isnan(features)
            counts = known.sum(axis=0)
            mean = np.where(counts > 0, np.nansum(features, axis=0) / np.maximum(counts, 1), 0.0)
            variance = np.where(
                counts > 0,
                np.nansum((features - mean) ** 2, axis=0) / np.maximum(counts, 1),
                0.0,
            )
        scale = np.sqrt(variance)
        scale[scale < 1e-12] = 1.0
        standardized = _standardize(features, mean, scale)
        total = weights.sum()
        x_mean = weights @ standardized / total
        y_mean = float(weights @ labels / total)
        centered = standardized - x_mean
        gram = centered.T @ (centered * weights[:, None]) + l2 * np.eye(centered.shape[1])
        coef = np.linalg.solve(gram, centered.T @ (weights * (labels - y_mean)))
        return cls(mean=mean, scale=scale, coef=coef, intercept=y_mean - float(x_mean @ coef))

    def _predict(self, features: Matrix) -> Vector:
        return _standardize(features, self.mean, self.scale) @ self.coef + self.intercept

    def _params(self) -> dict[str, Any]:
        return {
            "mean": self.mean.tolist(),
            "scale": self.scale.tolist(),
            "coef": self.coef.tolist(),
            "intercept": self.intercept,
        }


def ranker_model(model: RankingModel, *, now: datetime) -> Model:
    """`model` as the ranker's `Model`: scores each batch of candidates with one
    `predict` call, with upload ages measured at `now`."""

    def score(items: Sequence[ModelCandidate]) -> list[float]:
        return model.predict(
            [
                ModelInput.for_candidate(
                    item.candidate,
                    item.similarity,
                    item.embedding,
                    item.channel_score,
                    now=now,
                    tags=item.tags,
                )
                for item in items
            ]
        )

    return score


def _standardize(features: Matrix, mean: Vector, scale: Vector) -> Matrix:
    return np.nan_to_num((features - mean) / scale, nan=0.0)


# Small-data settings: few leaves, a floor on leaf size, and deterministic training.
LIGHTGBM_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 10,
    "feature_fraction": 0.8,
    "lambda_l2": 1.0,
    "seed": 0,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
    "verbosity": -1,
}
LIGHTGBM_ROUNDS = 200


class LightGBMModel(RankingModel):
    """A LightGBM regressor on the raw features (NaN means unknown)."""

    kind: ModelKind = "lightgbm"

    def __init__(self, booster: lgb.Booster) -> None:
        self.booster = booster

    @classmethod
    def fit(cls, features: Matrix, labels: Vector, weights: Vector) -> "LightGBMModel":
        dataset = lgb.Dataset(
            features,
            label=labels,
            weight=weights,
            feature_name=list(FEATURE_NAMES),
            params={"verbosity": -1},
        )
        return cls(lgb.train(LIGHTGBM_PARAMS, dataset, num_boost_round=LIGHTGBM_ROUNDS))

    def _predict(self, features: Matrix) -> Vector:
        return np.asarray(self.booster.predict(features), dtype=np.float64)

    def _params(self) -> dict[str, Any]:
        return {"model": self.booster.model_to_string()}


# Files


def models_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / MODELS_DIR


def save_model(model: RankingModel, data_dir: Path | None = None) -> str:
    """Write `model` to a new file; returns its path relative to `data_dir`."""
    directory = models_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}-{model.kind}.json"
    temporary = directory / f".{name}.tmp"
    temporary.write_text(json.dumps(model.to_dict()))
    temporary.replace(directory / name)
    return f"{MODELS_DIR}/{name}"


def read_model(path: str, data_dir: Path | None = None) -> RankingModel:
    """Load the model file at `path` (relative to `data_dir`). Raises OSError if it is
    missing and IncompatibleModelError if it can't be used with the current features."""
    data = json.loads(((data_dir or get_settings().data_dir) / path).read_text())
    return RankingModel.from_dict(data)


def delete_model_file(path: str, data_dir: Path | None = None) -> None:
    ((data_dir or get_settings().data_dir) / path).unlink(missing_ok=True)


# Registry


@dataclass(frozen=True)
class ModelVersion:
    id: int
    path: str  # relative to DATA_DIR
    kind: ModelKind
    feature_version: int
    spearman: float | None  # on the holdout; None when undefined
    mae: float  # on the holdout
    metrics: dict[str, Any]  # the training report (see homefeed_core.trainer)
    created_at: str  # ISO 8601 UTC
    active: bool
    activated_at: str | None  # ISO 8601 UTC

    @property
    def compatible(self) -> bool:
        """Whether it was trained with the current features (and so can be loaded)."""
        return self.feature_version == FEATURE_VERSION


@dataclass(frozen=True)
class ActiveModel:
    version: ModelVersion
    model: RankingModel


_COLUMNS = (
    "id, path, kind, feature_version, spearman, mae, metrics, created_at, active, activated_at"
)


def _version(row: Sequence[Any]) -> ModelVersion:
    id, path, kind, feature_version, spearman, mae, metrics, created_at, active, activated = row
    return ModelVersion(
        id=id,
        path=path,
        kind=cast(ModelKind, kind),
        feature_version=feature_version,
        spearman=spearman,
        mae=mae,
        metrics=json.loads(metrics),
        created_at=created_at,
        active=bool(active),
        activated_at=activated,
    )


def list_model_versions(session: Session) -> list[ModelVersion]:
    """Every stored version, newest first."""
    rows = session.execute(text(f"SELECT {_COLUMNS} FROM model_versions ORDER BY id DESC"))
    return [_version(row) for row in rows]


def get_model_version(session: Session, version_id: int) -> ModelVersion | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM model_versions WHERE id = :id"), {"id": version_id}
    ).one_or_none()
    return None if row is None else _version(row)


def get_active_version(session: Session) -> ModelVersion | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM model_versions WHERE active = 1")
    ).one_or_none()
    return None if row is None else _version(row)


def record_version(
    session: Session,
    *,
    path: str,
    kind: ModelKind,
    spearman: float | None,
    mae: float,
    metrics: Mapping[str, Any],
    now: datetime | None = None,
) -> ModelVersion:
    """Store a newly trained (inactive) version. The caller commits."""
    row = session.execute(
        text(
            f"""
            INSERT INTO model_versions (path, kind, feature_version, spearman, mae, metrics,
                                        created_at)
            VALUES (:path, :kind, :feature_version, :spearman, :mae, :metrics, :created_at)
            RETURNING {_COLUMNS}
            """
        ),
        {
            "path": path,
            "kind": kind,
            "feature_version": FEATURE_VERSION,
            "spearman": spearman,
            "mae": mae,
            "metrics": json.dumps(dict(metrics)),
            "created_at": format_timestamp(now or datetime.now(UTC)),
        },
    ).one()
    return _version(row)


def activate(
    session: Session, version_id: int, *, now: datetime | None = None
) -> ModelVersion | None:
    """Make `version_id` the active model (promotion or rollback); None if there is no
    such version. Raises IncompatibleModelError for a version trained with other
    features than the current ones. The caller commits."""
    version = get_model_version(session, version_id)
    if version is None:
        return None
    if not version.compatible:
        raise IncompatibleModelError(
            f"Model version {version_id} uses feature version {version.feature_version}, "
            f"not the current {FEATURE_VERSION}"
        )
    session.execute(text("UPDATE model_versions SET active = 0 WHERE active = 1"))
    session.execute(
        text("UPDATE model_versions SET active = 1, activated_at = :at WHERE id = :id"),
        {"id": version_id, "at": format_timestamp(now or datetime.now(UTC))},
    )
    return get_model_version(session, version_id)


def load_active_model(session: Session, *, data_dir: Path | None = None) -> ActiveModel | None:
    """The active version and its model, or None when there is none or it can't be
    loaded (missing file, other features); then ranking stays rules-only."""
    version = get_active_version(session)
    if version is None:
        return None
    try:
        return ActiveModel(version, read_model(version.path, data_dir))
    except (
        OSError,
        ValueError,
        KeyError,
        IncompatibleModelError,
        lgb.basic.LightGBMError,
    ) as error:
        logger.warning("Can't load active model version %d: %s", version.id, error)
        return None


def prune_versions(session: Session, *, keep: int = KEEP_VERSIONS) -> list[ModelVersion]:
    """Delete all but the newest `keep` versions, never the active one; returns those
    deleted so their files can be removed (`delete_model_file`) once committed."""
    stale = [
        version
        for index, version in enumerate(list_model_versions(session))
        if index >= keep and not version.active
    ]
    for version in stale:
        session.execute(text("DELETE FROM model_versions WHERE id = :id"), {"id": version.id})
    return stale
