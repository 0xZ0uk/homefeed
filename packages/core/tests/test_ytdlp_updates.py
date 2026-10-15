import hashlib
import io
import json
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from homefeed_core import ytdlp_updates
from homefeed_core.config import get_settings
from homefeed_core.gateway.ytdlp import js_runtime_options
from homefeed_core.ytdlp_updates import (
    YtDlpUpdateError,
    activate,
    is_newer,
    parse_version,
    update,
)

BUNDLED = "2026.8.19"
NEWER = "2026.9.1"
WHEEL_URL = "https://files.example/yt_dlp-{v}-py3-none-any.whl"
EJS_URL = "https://files.example/yt_dlp_ejs-0.9.0-py3-none-any.whl"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "homefeed.sqlite"))
    monkeypatch.delenv("YTDLP_AUTO_UPDATE", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ytdlp_updates, "bundled_version", lambda: BUNDLED)
    monkeypatch.setattr(ytdlp_updates, "_activated", None)
    monkeypatch.setattr(ytdlp_updates, "_activate_ran", False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "yt_dlp", raising=False)  # as at process start
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_wheel(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def yt_dlp_files(version: str) -> dict[str, str]:
    return {
        "yt_dlp/__init__.py": "",
        "yt_dlp/version.py": f"__version__ = '{version}'\n",
    }


def install_version(directory: Path, version: str, *, complete: bool = True) -> Path:
    path = directory / version
    (path / "yt_dlp").mkdir(parents=True)
    if complete:
        (path / "yt_dlp" / "__init__.py").write_text("")
        (path / "yt_dlp" / "version.py").write_text(f"__version__ = '{version}'\n")
    return path


class FakePyPI:
    """Answers the update's requests from memory, recording them."""

    def __init__(self, version: str = NEWER, *, sha_override: str | None = None) -> None:
        self.requests: list[str] = []
        yt_dlp_wheel = make_wheel(yt_dlp_files(version))
        ejs_wheel = make_wheel({"yt_dlp_ejs/__init__.py": "version = '0.9.0'\n"})
        url = WHEEL_URL.format(v=version)
        self.pages: dict[str, bytes] = {
            "https://pypi.org/pypi/yt-dlp/json": json.dumps(
                {
                    "info": {
                        "version": version,
                        "requires_dist": [
                            "pytest; extra == 'dev'",
                            "yt-dlp-ejs==0.9.0; extra == 'default'",
                        ],
                    },
                    "urls": [
                        {"packagetype": "sdist", "filename": "yt_dlp-x.tar.gz", "url": "no"},
                        {
                            "packagetype": "bdist_wheel",
                            "filename": f"yt_dlp-{version}-py3-none-any.whl",
                            "url": url,
                            "digests": {
                                "sha256": sha_override or hashlib.sha256(yt_dlp_wheel).hexdigest()
                            },
                        },
                    ],
                }
            ).encode(),
            "https://pypi.org/pypi/yt-dlp-ejs/0.9.0/json": json.dumps(
                {
                    "urls": [
                        {
                            "packagetype": "bdist_wheel",
                            "filename": "yt_dlp_ejs-0.9.0-py3-none-any.whl",
                            "url": EJS_URL,
                            "digests": {"sha256": hashlib.sha256(ejs_wheel).hexdigest()},
                        }
                    ]
                }
            ).encode(),
            url: yt_dlp_wheel,
            EJS_URL: ejs_wheel,
        }

    def __call__(self, url: str) -> bytes:
        self.requests.append(url)
        return self.pages[url]


def enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTDLP_AUTO_UPDATE", "true")
    get_settings.cache_clear()


def test_version_comparison() -> None:
    assert parse_version("2026.08.19") == (2026, 8, 19)
    assert is_newer("2026.8.19.232845", "2026.8.19")
    assert is_newer("2026.10.1", "2026.9.30")  # numeric, not lexicographic
    assert not is_newer("2026.8.19", "2026.08.19")
    with pytest.raises(ValueError):
        parse_version("../evil")


def test_js_runtime_options() -> None:
    assert js_runtime_options(None) == {}
    assert js_runtime_options("") == {}
    assert js_runtime_options("/opt/app/electron") == {
        "js_runtimes": {"node": {"path": "/opt/app/electron"}}
    }


def test_js_runtime_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_settings().js_runtime is None
    monkeypatch.setenv("HOMEFEED_JS_RUNTIME", "/opt/app/electron")
    get_settings.cache_clear()
    assert get_settings().js_runtime == "/opt/app/electron"


def test_activate_prepends_a_newer_complete_update(monkeypatch: pytest.MonkeyPatch) -> None:
    enable(monkeypatch)
    directory = get_settings().data_dir / "ytdlp"
    path = install_version(directory, NEWER)
    (directory / "current").write_text(NEWER)

    activate()

    assert sys.path[0] == str(path)
    versions = ytdlp_updates.versions()
    assert (versions.bundled, versions.active, versions.pending) == (BUNDLED, NEWER, None)


@pytest.mark.parametrize("case", ["disabled", "no_marker", "not_newer", "incomplete", "garbage"])
def test_activate_falls_back_to_the_bundled_version(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    if case != "disabled":
        enable(monkeypatch)
    directory = get_settings().data_dir / "ytdlp"
    before = list(sys.path)
    if case == "not_newer":
        install_version(directory, BUNDLED)
        (directory / "current").write_text(BUNDLED)
    elif case == "incomplete":
        install_version(directory, NEWER, complete=False)
        (directory / "current").write_text(NEWER)
    elif case == "garbage":
        directory.mkdir(parents=True)
        (directory / "current").write_text("../../etc")
    elif case == "disabled":
        install_version(directory, NEWER)
        (directory / "current").write_text(NEWER)

    activate()

    assert sys.path == before
    assert ytdlp_updates.versions().active == BUNDLED


def test_versions_report_a_pending_update() -> None:
    directory = get_settings().data_dir / "ytdlp"
    directory.mkdir(parents=True)
    (directory / "current").write_text(NEWER)

    versions = ytdlp_updates.versions()

    assert (versions.active, versions.pending) == (BUNDLED, NEWER)


def test_update_installs_atomically_and_marks_current(tmp_path: Path) -> None:
    pypi = FakePyPI()

    assert update(pypi, tmp_path / "data") == NEWER

    directory = tmp_path / "data" / "ytdlp"
    assert (directory / "current").read_text().strip() == NEWER
    assert ytdlp_updates.installed_version(directory / NEWER) == NEWER
    assert (directory / NEWER / "yt_dlp_ejs" / "__init__.py").is_file()  # the pinned solver
    assert [p.name for p in directory.iterdir() if p.name.startswith(".tmp-")] == []


def test_update_skips_when_not_newer(tmp_path: Path) -> None:
    pypi = FakePyPI(version=BUNDLED)

    assert update(pypi, tmp_path / "data") is None

    assert pypi.requests == ["https://pypi.org/pypi/yt-dlp/json"]
    assert not (tmp_path / "data" / "ytdlp" / "current").exists()


def test_update_skips_when_the_marked_version_is_current(tmp_path: Path) -> None:
    directory = tmp_path / "data" / "ytdlp"
    install_version(directory, NEWER)
    (directory / "current").write_text(NEWER)

    assert update(FakePyPI(), tmp_path / "data") is None


def test_update_rejects_a_checksum_mismatch(tmp_path: Path) -> None:
    pypi = FakePyPI(sha_override="0" * 64)

    with pytest.raises(YtDlpUpdateError, match="Checksum mismatch"):
        update(pypi, tmp_path / "data")

    directory = tmp_path / "data" / "ytdlp"
    assert list(directory.iterdir()) == []  # nothing installed, no temp leftovers


def test_update_rejects_a_wheel_that_escapes_the_directory(tmp_path: Path) -> None:
    pypi = FakePyPI()
    evil = make_wheel({"../escape.py": "x"})
    url = WHEEL_URL.format(v=NEWER)
    pypi.pages[url] = evil
    release = json.loads(pypi.pages["https://pypi.org/pypi/yt-dlp/json"])
    release["urls"][1]["digests"]["sha256"] = hashlib.sha256(evil).hexdigest()
    pypi.pages["https://pypi.org/pypi/yt-dlp/json"] = json.dumps(release).encode()

    with pytest.raises(YtDlpUpdateError, match="Unsafe path"):
        update(pypi, tmp_path / "data")

    assert not (tmp_path / "data" / "ytdlp" / "escape.py").exists()


def test_update_prunes_but_keeps_the_previous_version(tmp_path: Path) -> None:
    directory = tmp_path / "data" / "ytdlp"
    for old in ("2026.7.1", "2026.8.25"):
        install_version(directory, old)
    (directory / ".tmp-stale").mkdir()

    update(FakePyPI(), tmp_path / "data")

    assert sorted(p.name for p in directory.iterdir()) == ["2026.8.25", NEWER, "current"]


def test_entry_points_activate_before_yt_dlp_is_imported(tmp_path: Path) -> None:
    """Importing the API and worker packages (and their gateway) must not load yt-dlp
    before `activate()` ran, or an update couldn't take over."""
    script = (
        "import sys\n"
        "import homefeed_api, homefeed_worker\n"
        "assert 'yt_dlp' not in sys.modules, 'yt_dlp imported by the package inits'\n"
        "import homefeed_api.main, homefeed_worker.scheduler, homefeed_core.jobs\n"
        "assert 'yt_dlp' in sys.modules\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "DATA_DIR": str(tmp_path / "data"),
        "DATABASE_PATH": str(tmp_path / "data" / "homefeed.sqlite"),
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_activate_runs_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTDLP_AUTO_UPDATE", "true")
    get_settings.cache_clear()
    calls: list[int] = []
    monkeypatch.setattr(ytdlp_updates, "updates_dir", lambda: calls.append(1) or Path("/nope"))
    ytdlp_updates.activate()
    ytdlp_updates.activate()
    assert calls == [1]
