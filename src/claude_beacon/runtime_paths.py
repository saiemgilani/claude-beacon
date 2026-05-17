"""Cross-platform paths via platformdirs."""

from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir

_APP = "claude-beacon"

CONFIG_DIR = Path(user_config_dir(_APP))
CACHE_DIR = Path(user_cache_dir(_APP))

CONFIG_FILE = CONFIG_DIR / "config.toml"
LOCK_FILE = CACHE_DIR / "daemon.lock"
PID_FILE = CACHE_DIR / "daemon.pid"
STATE_FILE = CACHE_DIR / "state"
LOG_FILE = CACHE_DIR / "daemon.log"


def ensure_dirs() -> None:
    """Create config and cache dirs if missing. Idempotent."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
