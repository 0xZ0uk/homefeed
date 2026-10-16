"""Which browser yt-dlp takes YouTube cookies from, for when YouTube asks to "sign in to
confirm you're not a bot" (it does that to IPs it throttles).

The setting (`ytdlp_cookies_from_browser`, on the settings screen or in
YTDLP_COOKIES_FROM_BROWSER) is yt-dlp's --cookies-from-browser value:
BROWSER[+KEYRING][:PROFILE][::CONTAINER], e.g. "firefox", "chrome:Profile 1" or, for a
Firefox-based browser yt-dlp doesn't know, "firefox:/path/to/the/profile".

`find_browser_profiles` lists the profiles on this machine that have a cookie database,
for the settings screen to offer. Nothing in here imports yt-dlp (only the Gateway may);
the Gateway reads the cookies (see `gateway.ytdlp.cookie_options`).
"""

import configparser
import json
import logging
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# What yt-dlp can read cookies from (a test checks these match yt-dlp's).
CHROMIUM_BROWSERS = frozenset({"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"})
BROWSERS = CHROMIUM_BROWSERS | {"firefox", "safari"}
KEYRINGS = frozenset({"KWALLET", "KWALLET5", "KWALLET6", "GNOMEKEYRING", "BASICTEXT"})
MAX_SPEC_LENGTH = 1000

_SPEC = re.compile(
    r"""(?x)
    (?P<name>[^+:]+)
    (?:\s*\+\s*(?P<keyring>[^:]+))?
    (?:\s*:\s*(?!:)(?P<profile>.+?))?
    (?:\s*::\s*(?P<container>.+))?
    """
)


@dataclass(frozen=True)
class BrowserCookies:
    """A parsed --cookies-from-browser value."""

    browser: str
    profile: str | None = None
    keyring: str | None = None
    container: str | None = None


@dataclass(frozen=True)
class BrowserProfile:
    """A browser profile with a cookie database: `value` is the setting that reads it."""

    label: str
    value: str


def parse_browser_spec(spec: str) -> BrowserCookies:
    """Parse BROWSER[+KEYRING][:PROFILE][::CONTAINER] like yt-dlp does, expanding `~` in
    the profile. Raises `ValueError` for anything yt-dlp wouldn't accept."""
    spec = spec.strip()
    if len(spec) > MAX_SPEC_LENGTH:
        raise ValueError(f"The browser is longer than {MAX_SPEC_LENGTH} characters")
    match = _SPEC.fullmatch(spec)
    if match is None:
        raise ValueError(f"Not a browser yt-dlp can read cookies from: {spec!r}")
    name, keyring, profile, container = match.group("name", "keyring", "profile", "container")
    browser = name.strip().lower()
    if browser not in BROWSERS:
        raise ValueError(
            f"yt-dlp can't read cookies from {browser!r}; it supports {', '.join(sorted(BROWSERS))}"
        )
    if keyring is not None:
        keyring = keyring.strip().upper()
        if keyring not in KEYRINGS:
            raise ValueError(
                f"Unknown keyring {keyring!r}; yt-dlp supports {', '.join(sorted(KEYRINGS))}"
            )
    return BrowserCookies(
        browser=browser,
        profile=str(Path(profile).expanduser()) if profile else None,
        keyring=keyring,
        container=container,
    )


def find_browser_profiles() -> list[BrowserProfile]:
    """Browser profiles on this machine with a cookie database, Firefox-based ones first
    (their cookies aren't encrypted, so they work without a keyring). Never raises."""
    profiles: list[BrowserProfile] = []
    try:
        profiles.extend(_firefox_profiles())
        profiles.extend(_chromium_profiles())
        safari = Path.home() / "Library/Containers/com.apple.Safari/Data/Library/Cookies"
        if sys.platform == "darwin" and (safari / "Cookies.binarycookies").is_file():
            profiles.append(BrowserProfile("Safari", "safari"))
    except Exception:  # an odd profile layout mustn't break the settings screen
        logger.warning("Couldn't list browser profiles", exc_info=True)
    return list({profile.value: profile for profile in profiles}.values())


def _firefox_roots() -> Iterator[tuple[str, Path]]:
    """(browser name, directory holding its profiles) for Firefox and its forks."""
    home = Path.home()
    if sys.platform in ("win32", "cygwin"):
        appdata = Path(os.environ.get("APPDATA", home / "AppData/Roaming"))
        for name, path in (
            ("Firefox", "Mozilla/Firefox/Profiles"),
            ("Zen", "zen/Profiles"),
            ("LibreWolf", "librewolf/Profiles"),
            ("Floorp", "Floorp/Profiles"),
            ("Waterfox", "Waterfox/Profiles"),
        ):
            yield name, appdata / path
    elif sys.platform == "darwin":
        support = home / "Library/Application Support"
        for name, path in (
            ("Firefox", "Firefox/Profiles"),
            ("Zen", "zen/Profiles"),
            ("LibreWolf", "librewolf/Profiles"),
            ("Floorp", "Floorp/Profiles"),
            ("Waterfox", "Waterfox/Profiles"),
        ):
            yield name, support / path
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
        for name, path in (
            ("Firefox", config / "mozilla/firefox"),
            ("Firefox", home / ".mozilla/firefox"),
            ("Firefox", home / ".var/app/org.mozilla.firefox/.mozilla/firefox"),
            ("Firefox", home / "snap/firefox/common/.mozilla/firefox"),
            ("Zen", config / "zen"),
            ("Zen", home / ".zen"),
            ("Zen", home / ".var/app/app.zen_browser.zen/.zen"),
            ("LibreWolf", home / ".librewolf"),
            ("LibreWolf", home / ".var/app/io.gitlab.librewolf-community/.librewolf"),
            ("Floorp", home / ".floorp"),
            ("Waterfox", home / ".waterfox"),
        ):
            yield name, path


def _firefox_profiles() -> Iterator[BrowserProfile]:
    for browser, root in _firefox_roots():
        if not root.is_dir():
            continue
        names = _firefox_profile_names(root)
        directories = [path for path in root.iterdir() if (path / "cookies.sqlite").is_file()]
        # The most recently used profile first.
        directories.sort(key=lambda path: (path / "cookies.sqlite").stat().st_mtime, reverse=True)
        for directory in directories:
            name = names.get(directory.resolve()) or directory.name.partition(".")[2]
            label = f"{browser} ({name})" if name else browser
            yield BrowserProfile(label, f"firefox:{directory}")


def _firefox_profile_names(root: Path) -> dict[Path, str]:
    """Profile directory -> the name profiles.ini gives it ("default-release", ...)."""
    ini = configparser.ConfigParser(interpolation=None)
    try:
        ini.read(root / "profiles.ini", encoding="utf-8")
    except configparser.Error:
        return {}
    names: dict[Path, str] = {}
    for section in ini.sections():
        path, name = (
            ini.get(section, "Path", fallback=None),
            ini.get(section, "Name", fallback=None),
        )
        if path and name:
            relative = ini.get(section, "IsRelative", fallback="1") == "1"
            names[((root / path) if relative else Path(path)).resolve()] = name
    return names


def _chromium_roots() -> Iterator[tuple[str, str, Path]]:
    """(label, yt-dlp browser name, user data directory) for Chromium-based browsers."""
    home = Path.home()
    if sys.platform in ("win32", "cygwin"):
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        for label, browser, path in (
            ("Chrome", "chrome", "Google/Chrome/User Data"),
            ("Chromium", "chromium", "Chromium/User Data"),
            ("Brave", "brave", "BraveSoftware/Brave-Browser/User Data"),
            ("Edge", "edge", "Microsoft/Edge/User Data"),
            ("Vivaldi", "vivaldi", "Vivaldi/User Data"),
        ):
            yield label, browser, local / path
    elif sys.platform == "darwin":
        support = home / "Library/Application Support"
        for label, browser, path in (
            ("Chrome", "chrome", "Google/Chrome"),
            ("Chromium", "chromium", "Chromium"),
            ("Brave", "brave", "BraveSoftware/Brave-Browser"),
            ("Edge", "edge", "Microsoft Edge"),
            ("Vivaldi", "vivaldi", "Vivaldi"),
        ):
            yield label, browser, support / path
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
        for label, browser, path in (
            ("Chrome", "chrome", "google-chrome"),
            ("Chromium", "chromium", "chromium"),
            ("Brave", "brave", "BraveSoftware/Brave-Browser"),
            ("Edge", "edge", "microsoft-edge"),
            ("Vivaldi", "vivaldi", "vivaldi"),
        ):
            yield label, browser, config / path


def _chromium_profiles() -> Iterator[BrowserProfile]:
    for label, browser, root in _chromium_roots():
        if not root.is_dir():
            continue
        names = _chromium_profile_names(root)
        for directory in sorted(root.iterdir()):
            if directory.name != "Default" and not directory.name.startswith("Profile "):
                continue
            if not any((directory / p).is_file() for p in ("Cookies", "Network/Cookies")):
                continue
            name = names.get(directory.name, directory.name)
            yield BrowserProfile(f"{label} ({name})", f"{browser}:{directory.name}")


def _chromium_profile_names(root: Path) -> dict[str, str]:
    """Profile directory name -> the name the user gave it, from `Local State`."""
    try:
        state = json.loads((root / "Local State").read_text(encoding="utf-8"))
        cache = state["profile"]["info_cache"]
        return {key: str(value["name"]) for key, value in cache.items() if value.get("name")}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
