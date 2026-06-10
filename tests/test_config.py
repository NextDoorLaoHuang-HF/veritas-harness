import json
import os
from types import SimpleNamespace

import toml

from research import cli
from research.config import load_config


def test_default_reader_selfhost_is_not_machine_bound(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cfg = load_config()

    reader = cfg["reader_selfhost"]
    assert reader["dir"] == ""
    assert reader["pid_file"] == ""
    assert reader["puppeteer_cache_dir"] == ""
    forbidden_reader_dir = "/" + "/".join(["opt", "reader-selfhost"])
    forbidden_user_prefix = "/" + "Users" + "/"
    assert forbidden_reader_dir not in json.dumps(reader)
    assert forbidden_user_prefix not in json.dumps(reader)


def test_config_init_writes_reader_selfhost_section(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cli.cmd_config(SimpleNamespace(action="init", key=None, value=None))

    config_path = tmp_path / "xdg" / "research-cli" / "config.toml"
    cfg = toml.load(str(config_path))

    assert cfg["reader_selfhost"]["dir"] == ""
    assert cfg["reader_selfhost"]["command"] == "node src/server.js"
    assert cfg["reader_selfhost"]["port"] == 3099
    assert cfg["reader_selfhost"]["pid_file"] == ""
    assert cfg["reader_selfhost"]["puppeteer_cache_dir"] == ""
    forbidden_reader_dir = "/" + "/".join(["opt", "reader-selfhost"])
    forbidden_user_prefix = "/" + "Users" + "/"
    config_text = config_path.read_text()
    assert forbidden_reader_dir not in config_text
    assert forbidden_user_prefix not in config_text


def test_config_template_documents_reader_selfhost_without_absolute_defaults():
    text = open("config.toml.example", encoding="utf-8").read()

    assert "[reader_selfhost]" in text
    assert 'dir = ""' in text
    assert 'pid_file = ""' in text
    assert 'puppeteer_cache_dir = ""' in text
    forbidden_reader_dir = "/" + "/".join(["opt", "reader-selfhost"])
    forbidden_user_prefix = "/" + "Users" + "/"
    assert forbidden_reader_dir not in text
    assert forbidden_user_prefix not in text
