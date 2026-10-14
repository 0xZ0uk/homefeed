"""Self-updating yt-dlp, for installs that can't be rebuilt when YouTube breaks it.

YouTube changes often, and a yt-dlp release usually follows within days. With
`YTDLP_AUTO_UPDATE` on, the worker (`update()`, daily) downloads the newest pure-Python
yt-dlp wheel from PyPI, together with the `yt-dlp-ejs` it pins (the YouTube challenge
solver scripts; yt-dlp only accepts the same major.minor), and unpacks both into
`DATA_DIR/ytdlp/<version>/`. `DATA_DIR/ytdlp/current` names the version to use.

`activate()` runs at process start, before anything imports yt-dlp (the API and worker
packages call it from their `__init__`): if the marked version is newer than the bundled
one it puts that directory first on `sys.path`. A new version therefore takes effect on
the next restart. Any problem falls back to the bundled yt-dlp. Nothing in here imports
yt-dlp (only the Gateway may).
"""

import hashlib
import io
import json
import logging
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from homefeed_core.config import get_settings

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi"
UPDATES_DIRNAME = "ytdlp"
CURRENT_MARKER = "current"
# Versions kept (the newest and the one before it, for rollback by hand).
KEEP_VERSIONS = 2
TIMEOUT_SECONDS = 30.0
MAX_WHEEL_BYTES = 50 * 1024 * 1024
_TMP_PREFIX = ".tmp-"
_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")
_EJS_PIN = re.compile(r"^yt-dlp-ejs\s*==\s*([\w.]+)\s*;.*extra\s*==\s*['\"]default['\"]")

type Fetch = Callable[[str], bytes]


class YtDlpUpdateError(Exception):
    """An update couldn't be fetched, verified or installed."""


def parse_version(version: str) -> tuple[int, ...]:
    """yt-dlp's calendar versions ("2026.08.19", "2026.8.19.232845") as comparable ints."""
    if not _VERSION_RE.match(version):
        raise ValueError(f"Not a yt-dlp version: {version!r}")
    return tuple(int(part) for part in version.split("."))


def is_newer(candidate: str, than: str) -> bool:
    return parse_version(candidate) > parse_version(than)


def updates_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or get_settings().data_dir) / UPDATES_DIRNAME


def bundled_version() -> str | None:
    """The yt-dlp that came with the install (read from its metadata, not imported)."""
    try:
        return metadata.version("yt-dlp")
    except metadata.PackageNotFoundError:
        return None


def read_current(directory: Path) -> str | None:
    """The version `current` names, if it is a valid version."""
    try:
        version = (directory / CURRENT_MARKER).read_text().strip()
    except OSError:
        return None
    return version if _VERSION_RE.match(version) else None


def installed_version(path: Path) -> str | None:
    """The version of an unpacked yt-dlp in `path`, or None if it looks incomplete."""
    package = path / "yt_dlp"
    try:
        if not (package / "__init__.py").is_file():
            return None
        source = (package / "version.py").read_text()
    except OSError:
        return None
    match = re.search(r"""__version__\s*=\s*['"]([\d.]+)['"]""", source)
    return match.group(1) if match else None


@dataclass(frozen=True)
class YtDlpVersions:
    bundled: str | None
    active: str | None  # what this process runs: the update if activated, else the bundled
    pending: str | None  # a newer marked update that needs a restart to take effect


_activated: str | None = None
_activate_ran = False


def activate() -> None:
    """Put the marked yt-dlp update on `sys.path`, if updates are on and it's newer than
    the bundled one. Call before yt-dlp is first imported. Never raises."""
    global _activated, _activate_ran
    if _activate_ran:  # the API and the in-process worker both call this
        return
    _activate_ran = True
    try:
        if not get_settings().ytdlp_auto_update:
            return
        if "yt_dlp" in sys.modules:
            logger.warning("yt-dlp was imported before activate(); keeping the loaded version")
            return
        directory = updates_dir()
        marked = read_current(directory)
        bundled = bundled_version()
        if marked is None or (bundled is not None and not is_newer(marked, bundled)):
            return
        path = directory / marked
        if installed_version(path) != marked:
            logger.warning(
                "yt-dlp update %s in %s looks incomplete; using the bundled one", marked, path
            )
            return
        sys.path.insert(0, str(path))
        _activated = marked
        logger.info("Using yt-dlp %s from %s (bundled: %s)", marked, path, bundled)
    except Exception:
        logger.exception("Couldn't activate the yt-dlp update; using the bundled one")


def versions() -> YtDlpVersions:
    """Bundled, running and pending yt-dlp versions, for the status page."""
    bundled = bundled_version()
    active = _activated or bundled
    marked = read_current(updates_dir())
    pending = marked if marked and (active is None or is_newer(marked, active)) else None
    return YtDlpVersions(bundled=bundled, active=active, pending=pending)


def http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "homefeed"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(MAX_WHEEL_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise YtDlpUpdateError(f"Can't fetch {url}: {error}") from error
    if len(data) > MAX_WHEEL_BYTES:
        raise YtDlpUpdateError(f"{url} is larger than {MAX_WHEEL_BYTES} bytes")
    return data


@dataclass(frozen=True)
class _Wheel:
    url: str
    sha256: str


def _universal_wheel(release: dict[str, Any]) -> _Wheel:
    for file in release.get("urls", []):
        if file.get("packagetype") == "bdist_wheel" and str(file.get("filename", "")).endswith(
            "-py3-none-any.whl"
        ):
            return _Wheel(url=file["url"], sha256=file["digests"]["sha256"].lower())
    raise YtDlpUpdateError("The release has no py3-none-any wheel")


def _release_json(fetch: Fetch, project: str, version: str | None = None) -> dict[str, Any]:
    url = f"{PYPI_URL}/{project}/{version}/json" if version else f"{PYPI_URL}/{project}/json"
    try:
        release = json.loads(fetch(url))
    except json.JSONDecodeError as error:
        raise YtDlpUpdateError(f"Non-JSON answer from {url}: {error}") from error
    if not isinstance(release, dict):
        raise YtDlpUpdateError(f"Unexpected answer from {url}")
    return release


def _extract_wheel(wheel: _Wheel, fetch: Fetch, destination: Path) -> None:
    data = fetch(wheel.url)
    if hashlib.sha256(data).hexdigest() != wheel.sha256:
        raise YtDlpUpdateError(f"Checksum mismatch for {wheel.url}")
    root = destination.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise YtDlpUpdateError(f"Unsafe path in the wheel: {member.filename}")
        archive.extractall(destination)


def _write_current(directory: Path, version: str) -> None:
    temporary = directory / f"{_TMP_PREFIX}{CURRENT_MARKER}"
    temporary.write_text(version + "\n")
    os.replace(temporary, directory / CURRENT_MARKER)


def _installed_versions(directory: Path) -> list[str]:
    found = [
        entry.name
        for entry in directory.iterdir()
        if entry.is_dir() and _VERSION_RE.match(entry.name)
    ]
    return sorted(found, key=parse_version, reverse=True)


def prune(directory: Path, keep: int = KEEP_VERSIONS) -> None:
    """Remove all but the `keep` newest versions and leftovers of failed installs."""
    for entry in directory.iterdir():
        if entry.name.startswith(_TMP_PREFIX) and entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
    for version in _installed_versions(directory)[keep:]:
        shutil.rmtree(directory / version, ignore_errors=True)


def update(fetch: Fetch = http_get, data_dir: Path | None = None) -> str | None:
    """Install the newest yt-dlp from PyPI if it's newer than the one in use, and mark it
    current; the version installed, or None if already up to date. Raises
    `YtDlpUpdateError`. It takes effect on the next restart."""
    directory = updates_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    release = _release_json(fetch, "yt-dlp")
    latest = str(release.get("info", {}).get("version", ""))
    try:
        newest = parse_version(latest)
    except ValueError as error:
        raise YtDlpUpdateError(str(error)) from error
    in_use = [v for v in (bundled_version(), read_current(directory)) if v]
    if in_use and newest <= max(parse_version(v) for v in in_use):
        logger.info("yt-dlp %s is up to date (latest: %s)", max(in_use, key=parse_version), latest)
        return None

    wheels = [_universal_wheel(release)]
    # The solver scripts yt-dlp needs for YouTube; it pins the exact release.
    for requirement in release["info"].get("requires_dist") or []:
        if match := _EJS_PIN.match(requirement):
            wheels.append(_universal_wheel(_release_json(fetch, "yt-dlp-ejs", match.group(1))))
            break

    temporary = directory / f"{_TMP_PREFIX}{latest}-{uuid.uuid4().hex[:8]}"
    target = directory / latest
    try:
        temporary.mkdir()
        for wheel in wheels:
            _extract_wheel(wheel, fetch, temporary)
        if installed_version(temporary) != latest:
            raise YtDlpUpdateError(f"The wheel doesn't contain yt-dlp {latest}")
        if target.exists():
            shutil.rmtree(target)
        os.rename(temporary, target)  # atomic: same directory
    except (OSError, zipfile.BadZipFile) as error:
        raise YtDlpUpdateError(f"Couldn't install yt-dlp {latest}: {error}") from error
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    _write_current(directory, latest)
    prune(directory)
    logger.info("Installed yt-dlp %s; it takes effect when Homefeed restarts", latest)
    return latest
