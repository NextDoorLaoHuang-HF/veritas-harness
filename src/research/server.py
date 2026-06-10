import os
import shlex
import sys
import time
import json
import signal
import tempfile
import subprocess
from dataclasses import dataclass
from pathlib import Path

from research.config import load_config

DEFAULT_PORT = 3099
MAX_WAIT_SECONDS = 30


@dataclass(frozen=True)
class ReaderRuntime:
    reader_dir: Path | None
    command: list[str]
    port: int
    pid_file: Path
    puppeteer_cache: Path


def _reader_config() -> dict:
    return load_config().get("reader_selfhost", {})


def _runtime(port: int | None = None) -> ReaderRuntime:
    cfg = _reader_config()
    configured_dir = str(cfg.get("dir", "") or "").strip()
    reader_dir = Path(configured_dir).expanduser() if configured_dir else None
    command = shlex.split(str(cfg.get("command") or "node src/server.js"))
    runtime_port = int(port or cfg.get("port") or DEFAULT_PORT)

    pid_file_value = str(cfg.get("pid_file", "") or "").strip()
    pid_file = Path(pid_file_value).expanduser() if pid_file_value else Path(tempfile.gettempdir()) / f"veritas-reader-selfhost-{runtime_port}.pid"

    cache_value = str(cfg.get("puppeteer_cache_dir", "") or "").strip()
    if cache_value:
        puppeteer_cache = Path(cache_value).expanduser()
    elif reader_dir is not None:
        puppeteer_cache = reader_dir / ".cache" / "puppeteer"
    else:
        puppeteer_cache = Path(tempfile.gettempdir()) / "veritas-reader-selfhost" / "puppeteer"

    return ReaderRuntime(
        reader_dir=reader_dir,
        command=command,
        port=runtime_port,
        pid_file=pid_file,
        puppeteer_cache=puppeteer_cache,
    )


def _config_required_result(port: int) -> dict:
    msg = "reader_selfhost.dir is not configured; set it to a local reader-selfhost checkout before starting the server"
    print(msg, file=sys.stderr)
    return {"status": "config_required", "port": port, "message": msg}


def _default_env(runtime: ReaderRuntime) -> dict:
    cfg = load_config()
    api_keys = cfg.get("api_keys", {})

    runtime.puppeteer_cache.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "PORT": str(runtime.port),
        "PUPPETEER_CACHE_DIR": str(runtime.puppeteer_cache),
        "BROWSER_DISABLE_SANDBOX": "true",
        "HEADLESS": "true",
        "ACCESS_LOG_ENABLED": "false",
        "REQUEST_RATE_LIMIT_ENABLED": "false",
    })
    env.setdefault("EXA_API_KEY", api_keys.get("exa_key", ""))
    env.setdefault("ANYSEARCH_API_KEY", api_keys.get("anysearch_key", ""))
    if api_keys.get("anysearch_anonymous", True):
        env.setdefault("ANYSEARCH_ANONYMOUS", "true")
    return env


def _is_running(pid_file: Path) -> tuple[bool, int | None]:
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
        except ValueError:
            pid_file.unlink(missing_ok=True)
            return False, None
        try:
            os.kill(pid, 0)
            return True, pid
        except OSError:
            pid_file.unlink(missing_ok=True)
    return False, None


def _wait_for_health(port: int, timeout: int = MAX_WAIT_SECONDS) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=5)
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _can_launch(runtime: ReaderRuntime) -> bool:
    return runtime.reader_dir is not None and runtime.reader_dir.exists()


def cmd_start(args) -> dict:
    runtime = _runtime(getattr(args, "port", None))
    if not _can_launch(runtime):
        return _config_required_result(runtime.port)

    running, pid = _is_running(runtime.pid_file)
    if running:
        print(f"reader-selfhost already running (pid={pid}, port={runtime.port})")
        return {"status": "already_running", "pid": pid, "port": runtime.port, "url": f"http://localhost:{runtime.port}"}

    env = _default_env(runtime)
    runtime.pid_file.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        runtime.command,
        cwd=str(runtime.reader_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    runtime.pid_file.write_text(str(proc.pid))

    if _wait_for_health(runtime.port):
        print(f"reader-selfhost started (pid={proc.pid}, port={runtime.port})")
        start_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {
            "status": "started",
            "pid": proc.pid,
            "port": runtime.port,
            "url": f"http://localhost:{runtime.port}",
            "start_time": start_time,
        }
    else:
        proc.kill()
        runtime.pid_file.unlink(missing_ok=True)
        print("reader-selfhost failed to start within timeout")
        return {"status": "timeout", "port": runtime.port}


def cmd_stop(args) -> dict:
    runtime = _runtime(getattr(args, "port", None))
    running, pid = _is_running(runtime.pid_file)
    if not running:
        print("reader-selfhost is not running")
        return {"status": "not_running"}

    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                break
        else:
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    runtime.pid_file.unlink(missing_ok=True)
    print(f"reader-selfhost stopped (pid={pid})")
    return {"status": "stopped", "pid": pid}


def cmd_status(args) -> dict:
    runtime = _runtime(getattr(args, "port", None))
    running, pid = _is_running(runtime.pid_file)
    if running:
        healthy = _wait_for_health(runtime.port, timeout=5)
        result = {
            "status": "running" if healthy else "degraded",
            "pid": pid,
            "port": runtime.port,
            "url": f"http://localhost:{runtime.port}",
        }
    elif runtime.reader_dir is None:
        result = {"status": "config_required", "port": runtime.port, "message": "reader_selfhost.dir is not configured"}
    else:
        result = {"status": "stopped", "port": runtime.port}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def ensure_running(port: int | None = None) -> int:
    """Start server if configured and not running; return its port, or 0 if unavailable."""
    runtime = _runtime(port)
    if not _can_launch(runtime):
        print("Warning: reader-selfhost dir is not configured or does not exist", file=sys.stderr)
        return 0

    running, pid = _is_running(runtime.pid_file)
    if running:
        return runtime.port

    env = _default_env(runtime)
    runtime.pid_file.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        runtime.command,
        cwd=str(runtime.reader_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    runtime.pid_file.write_text(str(proc.pid))

    if not _wait_for_health(runtime.port):
        proc.kill()
        runtime.pid_file.unlink(missing_ok=True)
        print("Warning: reader-selfhost failed to start", file=sys.stderr)
        return 0

    return runtime.port
