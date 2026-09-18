"""Keep the local Qlib daily data in step with the community snapshot it came from.

The data under ``QLIB_PROVIDER_URI`` is a release of chenditc/investment_data (``qlib_bin.tar.gz``, one
release per trading day). Syncing = check the latest release on GitHub, download the archive, verify its
sha256 against the release manifest, unpack it next to the current data and swap the directories, then
record the release in ``studio-data-source.json``. Runs in a background thread; ``run_sync`` refuses to
start while a backtest worker or an RD-Agent experiment is running, since they read the data files.
An optional daily schedule (``sync.json``: {"auto": bool, "hour": int}) does the same check once a day.
"""
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = "chenditc/investment_data"
ARCHIVE = "qlib_bin.tar.gz"
MANIFEST = "qlib_bin.manifest.json"
USER_AGENT = "rd-agent-studio"

_lock = threading.Lock()
_state = {"running": False, "phase": None, "progress": None, "started_at": None, "finished_at": None, "error": None, "log": []}
_remote_cache = {"checked_at": 0.0, "release": None}
_busy_check = lambda: False  # noqa: E731 - replaced by configure()
_settings_path: Path | None = None
_scheduler_started = False


def configure(settings_path: Path, busy_check):
    """Called once from the blueprint: where to keep sync.json and how to tell whether workers are running."""
    global _settings_path, _busy_check, _scheduler_started
    _settings_path = settings_path
    _busy_check = busy_check
    if not _scheduler_started:
        _scheduler_started = True
        threading.Thread(target=_scheduler, name="studio-data-sync", daemon=True).start()


def provider_dir() -> Path:
    return Path(os.environ.get("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser()


def local_info() -> dict:
    root = provider_dir()
    calendar = root / "calendars" / "day.txt"
    dates = calendar.read_text().splitlines() if calendar.is_file() else []
    source = {}
    if (root / "studio-data-source.json").is_file():
        try:
            source = json.loads((root / "studio-data-source.json").read_text())
        except ValueError:
            source = {}
    return {"release": source.get("release"), "downloaded_at": source.get("downloaded_at"),
            "calendar_start": dates[0] if dates else None, "calendar_end": dates[-1] if dates else None, "path": str(root)}


def settings() -> dict:
    default = {"auto": False, "hour": 19, "last_auto_check": None}
    if _settings_path and _settings_path.is_file():
        try:
            return {**default, **json.loads(_settings_path.read_text())}
        except ValueError:
            pass
    return default


def save_settings(values: dict) -> dict:
    merged = {**settings(), **values}
    if _settings_path:
        _settings_path.parent.mkdir(parents=True, exist_ok=True)
        _settings_path.write_text(json.dumps(merged))
    return merged


def _get_json(url: str, timeout: int = 20) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    # An unauthenticated client gets 60 API calls an hour per IP; a token (GITHUB_TOKEN or GH_TOKEN) lifts that.
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _latest_tag_by_redirect(timeout: int = 20) -> str:
    """The latest release tag from the web redirect of /releases/latest, which is not API rate-limited."""
    request = urllib.request.Request(f"https://github.com/{REPO}/releases/latest", method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final = response.geturl()
    tag = final.rstrip("/").rsplit("/", 1)[-1]
    if not tag or tag == "latest":
        raise RuntimeError(f"Could not read the latest release tag from {final}")
    return urllib.parse.unquote(tag)


def check_remote(max_age: float = 900) -> dict:
    """The latest release (tag, published_at, archive url/size, manifest url), cached for 15 minutes.

    Uses the GitHub API; when that is rate-limited (HTTP 403/429) falls back to the release page's redirect for the
    tag and derives the download URLs (size and publish time then unknown). A stale cache beats an error."""
    now = time.time()
    if _remote_cache["release"] and now - _remote_cache["checked_at"] < max_age:
        return _remote_cache["release"]
    try:
        data = _get_json(f"https://api.github.com/repos/{REPO}/releases/latest")
        assets = {a["name"]: a for a in data.get("assets", [])}
        if ARCHIVE not in assets:
            raise RuntimeError(f"Latest release {data.get('tag_name')} has no {ARCHIVE}")
        release = {"release": data.get("tag_name"), "published_at": data.get("published_at"),
                   "archive_url": assets[ARCHIVE]["browser_download_url"], "archive_bytes": assets[ARCHIVE].get("size"),
                   "manifest_url": assets.get(MANIFEST, {}).get("browser_download_url")}
    except urllib.error.HTTPError as error:
        if error.code not in (403, 429):
            raise
        try:
            tag = _latest_tag_by_redirect()
        except Exception as fallback_error:  # noqa: BLE001
            if _remote_cache["release"]:
                return _remote_cache["release"]
            raise RuntimeError(f"GitHub API 限流（HTTP {error.code}），发布页也读不到：{fallback_error}") from fallback_error
        base = f"https://github.com/{REPO}/releases/download/{tag}"
        release = {"release": tag, "published_at": None, "archive_url": f"{base}/{ARCHIVE}", "archive_bytes": None,
                   "manifest_url": f"{base}/{MANIFEST}"}
    _remote_cache.update({"checked_at": now, "release": release})
    return release


def status() -> dict:
    with _lock:
        state = dict(_state)
        state["log"] = list(_state["log"][-12:])
    return {"local": local_info(), "settings": settings(), "sync": state,
            "remote": _remote_cache["release"], "remote_checked_at": _remote_cache["checked_at"] or None}


def _log(message: str, **fields):
    with _lock:
        _state.update(fields)
        _state["log"].append(f"{datetime.now().strftime('%H:%M:%S')} {message}")
        del _state["log"][:-50]


def _download(url: str, target: Path, expected_bytes: int | None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:
        total = int(response.headers.get("Content-Length") or expected_bytes or 0)
        done = 0
        last = 0.0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total and time.time() - last > 1:
                last = time.time()
                with _lock:
                    _state["progress"] = round(done / total, 3)


def _find_data_root(extracted: Path) -> Path:
    for candidate in [extracted, *extracted.iterdir()]:
        if (candidate / "calendars" / "day.txt").is_file():
            return candidate
    raise RuntimeError("Archive does not contain a Qlib data directory (no calendars/day.txt)")


def run_sync(force: bool = False) -> dict:
    """Start a sync in the background; returns the reason when it cannot start."""
    with _lock:
        if _state["running"]:
            return {"started": False, "reason": "同步已在进行"}
    if _busy_check():
        return {"started": False, "reason": "有回测或研究正在运行，等它们结束再同步"}
    try:
        remote = check_remote(max_age=0)
    except Exception as error:  # noqa: BLE001 - network failures are reported, not raised
        return {"started": False, "reason": f"无法访问 GitHub 发布页：{error}"}
    if not force and local_info().get("release") == remote["release"]:
        return {"started": False, "reason": f"已是最新版 {remote['release']}", "release": remote["release"]}
    with _lock:
        _state.update({"running": True, "phase": "starting", "progress": None, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "finished_at": None, "error": None, "log": []})
    threading.Thread(target=_sync_worker, args=(remote,), name="studio-data-sync-run", daemon=True).start()
    return {"started": True, "release": remote["release"]}


def _sync_worker(remote: dict):
    root = provider_dir()
    staging = root.parent / f"{root.name}.new"
    backup = root.parent / f"{root.name}.old"
    try:
        _log(f"下载 {remote['release']} 的 {ARCHIVE}（{(remote.get('archive_bytes') or 0) / 1e6:.0f} MB）", phase="downloading", progress=0.0)
        with tempfile.TemporaryDirectory(prefix="qlib-sync-", dir=root.parent) as tmp:
            archive = Path(tmp) / ARCHIVE
            _download(remote["archive_url"], archive, remote.get("archive_bytes"))
            digest = None
            if remote.get("manifest_url"):
                try:
                    manifest = _get_json(remote["manifest_url"])
                    digest = str(manifest.get("archive_sha256") or "").replace("sha256:", "") or None
                except Exception as error:  # noqa: BLE001
                    _log(f"未能读取 manifest（{error}），跳过校验")
            _log("校验并解包", phase="extracting", progress=None)
            sha = hashlib.sha256()
            with archive.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    sha.update(chunk)
            if digest and sha.hexdigest() != digest:
                raise RuntimeError("sha256 与 manifest 不符，放弃这次下载")
            extracted = Path(tmp) / "extracted"
            extracted.mkdir()
            with tarfile.open(archive) as tar:
                tar.extractall(extracted, filter="data")
            data_root = _find_data_root(extracted)
            if staging.exists():
                shutil.rmtree(staging)
            shutil.move(str(data_root), str(staging))
        calendar = (staging / "calendars" / "day.txt").read_text().splitlines()
        (staging / "studio-data-source.json").write_text(json.dumps({
            "source": remote["archive_url"], "release": remote["release"], "published_at": remote.get("published_at"),
            "downloaded_at": datetime.now(timezone.utc).isoformat(), "sha256": sha.hexdigest(), "archive_bytes": remote.get("archive_bytes"),
            "calendar_start": calendar[0], "calendar_end": calendar[-1], "kind": "community daily historical snapshot; not a live feed",
        }, indent=2))
        _log("替换数据目录", phase="swapping")
        if _busy_check():
            raise RuntimeError("替换前发现有任务在运行，已中止；新数据留在 .new 目录，稍后重试即可")
        if backup.exists():
            shutil.rmtree(backup)
        if root.exists():
            root.rename(backup)
        staging.rename(root)
        shutil.rmtree(backup, ignore_errors=True)
        _log(f"完成：数据到 {calendar[-1]}（版本 {remote['release']}）", phase="done", progress=1.0)
    except Exception as error:  # noqa: BLE001 - shown to the user
        _log(f"失败：{error}", phase="failed", error=str(error))
        if not root.exists() and backup.exists():
            backup.rename(root)
    finally:
        with _lock:
            _state["running"] = False
            _state["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _scheduler():
    """Once a day at the configured hour, sync when a newer release exists and nothing is running."""
    while True:
        try:
            conf = settings()
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if conf.get("auto") and now.hour >= int(conf.get("hour", 19)) and conf.get("last_auto_check") != today:
                save_settings({"last_auto_check": today})
                result = run_sync()
                _log(f"自动同步：{'已开始' if result.get('started') else result.get('reason')}")
        except Exception as error:  # noqa: BLE001
            _log(f"自动同步检查出错：{error}")
        time.sleep(600)
