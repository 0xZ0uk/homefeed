import json
import sqlite3
import sys
from pathlib import Path

import pytest

from homefeed_core.browser_cookies import (
    BROWSERS,
    KEYRINGS,
    BrowserCookies,
    BrowserProfile,
    find_browser_profiles,
    parse_browser_spec,
)
from homefeed_core.config import Settings, get_settings
from homefeed_core.gateway import CookieCheck, CookiesError, GatewayError
from homefeed_core.gateway.ytdlp import (
    ExtractRequest,
    _YtDlpLogger,  # pyright: ignore[reportPrivateUsage]
    check_cookies,
    cookie_options,
    cookie_sources,
    extract_info,
)
from homefeed_core.user_settings import UserSettings, default_user_settings

linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux profile locations")


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return tmp_path


def firefox_profile(directory: Path, cookies: dict[str, str]) -> Path:
    """A Firefox profile whose cookie database has `cookies` for .youtube.com."""
    directory.mkdir(parents=True)
    with sqlite3.connect(directory / "cookies.sqlite") as db:
        db.execute(
            "CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT, path TEXT,"
            " expiry INTEGER, isSecure INTEGER, originAttributes TEXT)"
        )
        db.executemany(
            "INSERT INTO moz_cookies VALUES ('.youtube.com', ?, ?, '/', 4102444800, 1, '')",
            cookies.items(),
        )
    return directory


def test_browsers_match_yt_dlp() -> None:
    assert cookie_sources() == (BROWSERS, KEYRINGS)


def test_parse_browser_spec() -> None:
    assert parse_browser_spec(" Firefox ") == BrowserCookies("firefox")
    assert parse_browser_spec("chromium+gnomekeyring:Profile 1::work") == BrowserCookies(
        "chromium", "Profile 1", "GNOMEKEYRING", "work"
    )
    assert parse_browser_spec("firefox:~/.config/zen/x.Default (release)") == BrowserCookies(
        "firefox", f"{Path.home()}/.config/zen/x.Default (release)"
    )
    for invalid in (":profile", "netscape", "chrome+wallet", "firefox:" + "x" * 1000):
        with pytest.raises(ValueError):
            parse_browser_spec(invalid)


def test_cookie_options() -> None:
    assert cookie_options(None, None) == {}
    assert cookie_options(" ", None) == {}
    assert cookie_options("chrome:Profile 1", None) == {
        "cookiesfrombrowser": ("chrome", "Profile 1", None, None)
    }
    assert cookie_options(None, Path("/data/cookies.txt")) == {"cookiefile": "/data/cookies.txt"}
    with pytest.raises(CookiesError):
        cookie_options("netscape", None)


def test_cookie_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = get_settings()
    assert (settings.ytdlp_cookies_from_browser, settings.ytdlp_cookies_file) == (None, None)
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "firefox")
    monkeypatch.setenv("YTDLP_COOKIES_FILE", str(tmp_path / "cookies.txt"))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.ytdlp_cookies_from_browser == "firefox"
    assert settings.ytdlp_cookies_file == tmp_path / "cookies.txt"


def test_the_user_setting_is_validated() -> None:
    defaults = default_user_settings(Settings(ytdlp_cookies_from_browser=" brave "))
    assert defaults.ytdlp_cookies_from_browser == "brave"
    values = defaults.model_dump()
    assert (
        UserSettings.model_validate(
            values | {"ytdlp_cookies_from_browser": " "}
        ).ytdlp_cookies_from_browser
        is None
    )
    with pytest.raises(ValueError, match="netscape"):
        UserSettings.model_validate(values | {"ytdlp_cookies_from_browser": "netscape"})


def test_check_cookies_reads_a_signed_in_profile(tmp_path: Path) -> None:
    signed_in = firefox_profile(
        tmp_path / "signed-in", {"LOGIN_INFO": "a", "SAPISID": "b", "PREF": "c"}
    )
    signed_out = firefox_profile(tmp_path / "signed-out", {"PREF": "c", "VISITOR_INFO1_LIVE": "d"})

    assert check_cookies(f"firefox:{signed_in}") == CookieCheck(3, signed_in=True)
    assert check_cookies(f"firefox:{signed_out}") == CookieCheck(2, signed_in=False)


def test_check_cookies_explains_what_went_wrong(tmp_path: Path) -> None:
    with pytest.raises(CookiesError, match="could not find firefox cookies database"):
        check_cookies(f"firefox:{tmp_path / 'missing'}")
    with pytest.raises(CookiesError, match="netscape"):
        check_cookies("netscape")
    with pytest.raises(CookiesError, match="Choose a browser"):
        check_cookies("")


def test_unreadable_cookies_are_left_out(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    missing = f"firefox:{tmp_path / 'missing'}"
    # Without network access the extraction still fails, but past the cookies.
    with pytest.raises(GatewayError) as error:
        extract_info(ExtractRequest("https://www.youtube.com/watch?v=aaaaaaaaaaa"), lambda: missing)
    assert "cookies" not in str(error.value)
    assert "going without" in caplog.text


def test_repeated_warnings_are_logged_once(caplog: pytest.LogCaptureFixture) -> None:
    log = _YtDlpLogger()
    for _ in range(300):  # e.g. once per cookie yt-dlp can't decrypt
        log.warning("cannot decrypt v11 cookies: no key found")
    log.warning("something else")
    assert log.warnings == ["cannot decrypt v11 cookies: no key found", "something else"]
    assert len(caplog.records) == 2


@linux_only
def test_find_browser_profiles(home: Path) -> None:
    firefox = firefox_profile(home / ".mozilla/firefox/abcd.default-release", {})
    (home / ".mozilla/firefox/efgh.empty").mkdir()  # no cookie database
    zen = firefox_profile(home / ".config/zen/wxyz.Default (release)", {})
    (home / ".config/zen/profiles.ini").write_text(
        "[Profile0]\nName=Work\nIsRelative=1\nPath=wxyz.Default (release)\n"
    )
    chrome = home / ".config/google-chrome"
    for profile in ("Default", "Profile 1"):
        (chrome / profile / "Network").mkdir(parents=True)
        (chrome / profile / "Network/Cookies").touch()
    (chrome / "Local State").write_text(
        json.dumps({"profile": {"info_cache": {"Profile 1": {"name": "Personal"}}}})
    )

    assert find_browser_profiles() == [
        BrowserProfile("Firefox (default-release)", f"firefox:{firefox}"),
        BrowserProfile("Zen (Work)", f"firefox:{zen}"),
        BrowserProfile("Chrome (Default)", "chrome:Default"),
        BrowserProfile("Chrome (Personal)", "chrome:Profile 1"),
    ]


@linux_only
def test_find_browser_profiles_without_browsers(home: Path) -> None:
    assert find_browser_profiles() == []
