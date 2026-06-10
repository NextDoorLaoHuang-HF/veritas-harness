import copy
import os
import toml
from pathlib import Path

DEFAULTS = {
    "search": {
        "default_limit": 10,
        "max_concurrent": 4,
    },
    "run_dir": {
        "base": ".research/runs",
    },
    "api_keys": {
        "yuandian_key": "",
    },
    "opencli": {
        "public_only": False,
        "timeout": 30,
        "inter_command_delay": 3.0,
        "default_sites": "",  # Comma-separated, empty = auto-routing
    },
    "reader_selfhost": {
        "url": "http://localhost:3099",
        "dir": "",
        "command": "node src/server.js",
        "port": 3099,
        "pid_file": "",
        "puppeteer_cache_dir": "",
    },
}

def load_config() -> dict:
    config = copy.deepcopy(DEFAULTS)

    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_path = Path(xdg_config) / "research-cli" / "config.toml"
    if config_path.exists():
        user_config = toml.load(str(config_path))
        for section, values in user_config.items():
            if section in config and isinstance(values, dict):
                config[section].update(values)
            else:
                config[section] = values

    env_map = {
        "YUANDIAN_API_KEY": ("api_keys", "yuandian_key"),
        "OPENCLI_TIMEOUT": ("opencli", "timeout"),
        "OPENCLI_PUBLIC_ONLY": ("opencli", "public_only"),
        "OPENCLI_DEFAULT_SITES": ("opencli", "default_sites"),
        "READER_SELFHOST_URL": ("reader_selfhost", "url"),
        "READER_SELFHOST_DIR": ("reader_selfhost", "dir"),
        "READER_SELFHOST_COMMAND": ("reader_selfhost", "command"),
        "READER_SELFHOST_PORT": ("reader_selfhost", "port"),
        "READER_SELFHOST_PID_FILE": ("reader_selfhost", "pid_file"),
        "READER_SELFHOST_PUPPETEER_CACHE_DIR": ("reader_selfhost", "puppeteer_cache_dir"),
    }
    for env_key, (section, key) in env_map.items():
        value = os.environ.get(env_key)
        if value is not None:
            if section not in config:
                config[section] = {}
            default_value = DEFAULTS.get(section, {}).get(key)
            if isinstance(default_value, bool):
                config[section][key] = value.lower() in {"1", "true", "yes", "on"}
            elif isinstance(default_value, int):
                config[section][key] = int(value)
            elif isinstance(default_value, float):
                config[section][key] = float(value)
            else:
                config[section][key] = value

    return config
