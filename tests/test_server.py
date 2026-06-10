from pathlib import Path
from types import SimpleNamespace

from research import server


def test_reader_selfhost_start_requires_configured_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "load_config", lambda: {
        "reader_selfhost": {
            "dir": "",
            "command": "node src/server.js",
            "port": 3099,
            "pid_file": str(tmp_path / "reader.pid"),
            "puppeteer_cache_dir": "",
        },
        "api_keys": {},
    })

    def fail_popen(*args, **kwargs):
        raise AssertionError("reader-selfhost must not be launched without an explicit configured dir")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server.cmd_start(SimpleNamespace(port=None))

    assert result["status"] == "config_required"
    assert "reader_selfhost.dir" in result["message"]


def test_reader_selfhost_runtime_uses_configured_directory(monkeypatch, tmp_path):
    reader_dir = tmp_path / "reader-selfhost"
    reader_dir.mkdir()
    pid_file = tmp_path / "reader.pid"
    cache_dir = tmp_path / "puppeteer-cache"

    monkeypatch.setattr(server, "load_config", lambda: {
        "reader_selfhost": {
            "dir": str(reader_dir),
            "command": "node src/server.js",
            "port": 4321,
            "pid_file": str(pid_file),
            "puppeteer_cache_dir": str(cache_dir),
        },
        "api_keys": {},
    })

    runtime = server._runtime()

    assert runtime.reader_dir == reader_dir
    assert runtime.command == ["node", "src/server.js"]
    assert runtime.port == 4321
    assert runtime.pid_file == pid_file
    assert runtime.puppeteer_cache == cache_dir
    forbidden_default = Path("/").joinpath("opt", "reader-selfhost")
    assert runtime.reader_dir != forbidden_default
