# claude-beacon

Drive a TP-Link **Kasa/Tapo** smart bulb — or fire **ntfy.sh / Discord / Slack / Home Assistant** webhooks — from [Claude Code](https://docs.anthropic.com/en/docs/claude-code) session state.

Cross-platform: Windows, macOS, Linux. Pure Python.

## What it does

Claude Code emits hook events (SessionStart, UserPromptSubmit, PreToolUse, Stop, Notification, SessionEnd…). `claude-beacon` maps these to four states and reflects them on a configured device:

| State | Trigger | Kasa default | HTTP default |
|---|---|---|---|
| `WORKING` | Prompt submit, tool use, plan mode | White/navy pulse | (no notification by default — too noisy) |
| `IDLE` | Stop, SessionStart | Solid sunset mango | (no notification by default) |
| `INPUT` | Permission, AskUserQuestion | Solid purple | Push notification |
| `OFF` | SessionEnd | Light off | Push notification |

## Install

```bash
pip install claude-beacon
```

Requires Python 3.11+.

## Quickstart — Kasa/Tapo bulb

**Prerequisite:** the bulb must already be on your home WiFi via the **Kasa Smart** (legacy) or **Tapo** (modern) mobile app. `claude-beacon` never sees your WiFi password — it just talks to the bulb's LAN IP.

```bash
claude-beacon setup --adapter kasa
```

The wizard discovers bulbs on your subnet (or accepts a manual IP for IoT-VLAN setups), prompts for TP-Link cloud credentials if you have a Tapo bulb, and tests the connection.

Then merge `settings.example.json` into `~/.claude/settings.json` and restart Claude Code.

## Quickstart — ntfy push notifications

ntfy.sh is free, requires no account, and works by channel name (treat the channel name like a password — anyone who knows it can read your notifications).

```bash
claude-beacon setup --adapter http
# choose [n] ntfy.sh
# wizard generates a random channel and sends a test notification
```

Subscribe to the generated channel URL on your phone using the [ntfy app](https://ntfy.sh).

## Config reference

Config lives at:
- **Windows:** `%LOCALAPPDATA%\claude-beacon\config.toml`
- **macOS:** `~/Library/Application Support/claude-beacon/config.toml`
- **Linux:** `~/.config/claude-beacon/config.toml`

### Kasa: single bulb

```toml
adapter = "kasa"

[kasa]
hosts = ["192.168.1.42"]
```

### Kasa: multiple bulbs (parallel mirror)

```toml
adapter = "kasa"

[kasa]
hosts = ["192.168.1.42", "192.168.1.43", "192.168.1.44"]
```

All bulbs react together. Per-bulb failures are warnings; only an all-bulb outage triggers a daemon reconnect.

### Kasa: Tapo with credentials

```toml
adapter = "kasa"

[kasa]
hosts    = ["192.168.1.42"]
username = "you@example.com"
password = "..."
```

### HTTP: ntfy.sh (INPUT + OFF only)

```toml
adapter = "http"

[http]
timeout_s = 5

[[http.endpoints.input]]
url     = "https://ntfy.sh/claude-beacon-7k3n9w2p"
method  = "POST"
body    = "Claude needs your input"
headers = { Title = "Claude Beacon", Priority = "high", Tags = "warning,bell" }

[[http.endpoints.off]]
url     = "https://ntfy.sh/claude-beacon-7k3n9w2p"
method  = "POST"
body    = "Session ended"
headers = { Title = "Claude Beacon", Priority = "low", Tags = "white_check_mark" }
```

### HTTP: Discord webhook

```toml
[[http.endpoints.input]]
url     = "https://discord.com/api/webhooks/<id>/<token>"
method  = "POST"
headers = { "Content-Type" = "application/json" }
body    = '{"content": "Claude needs your input"}'
```

### HTTP: Slack incoming webhook

```toml
[[http.endpoints.input]]
url     = "https://hooks.slack.com/services/<workspace>/<channel>/<token>"
method  = "POST"
headers = { "Content-Type" = "application/json" }
body    = '{"text": "Claude needs your input"}'
```

### HTTP: Home Assistant webhook

```toml
[[http.endpoints.input]]
url     = "http://homeassistant.local:8123/api/webhook/claude_input"
method  = "POST"
headers = { "Content-Type" = "application/json" }
body    = '{"state": "input"}'
```

(In HA, create an `Automation` triggered by `Webhook` with ID `claude_input`. No bearer token needed for webhook triggers.)

### HTTP: multi-target (ntfy + Discord on INPUT)

```toml
[[http.endpoints.input]]
url     = "https://ntfy.sh/claude-beacon-7k3n9w2p"
method  = "POST"
body    = "Claude needs your input"

[[http.endpoints.input]]
url     = "https://discord.com/api/webhooks/<id>/<token>"
method  = "POST"
headers = { "Content-Type" = "application/json" }
body    = '{"content": "Claude needs your input"}'
```

### Daemon overrides (optional)

```toml
[daemon]
tick_ms                   = 200      # state-file poll interval
debounce_ms               = 500      # idle->working transitions within this window are suppressed
idle_timeout_s            = 1800     # daemon auto-exits after this much continuous idle
health_interval_idle_s    = 60
health_interval_working_s = 10
reconnect_backoff_s       = [1, 2, 4, 8, 16]
```

## Architecture

```
Claude Code hook event
  -> python -m claude_beacon hook <state>
      (writes state atomically; spawns daemon if not alive; exits 0)
  -> python -m claude_beacon daemon (long-lived asyncio loop)
      -> DeviceAdapter.apply_state(state)
          -> Kasa bulb / HTTP webhook / your future adapter
```

Two adapters ship in v1:

- **`KasaAdapter`** — `python-kasa` (Kasa + Tapo). Streams a two-color animation for WORKING; sets solid HSV for IDLE/INPUT.
- **`HttpAdapter`** — `httpx`. Per-state opt-in (omit a state -> no request fires). Multi-endpoint fanout per state with fail-soft.

Adding a new adapter is one file in `src/claude_beacon/adapters/` plus one line in `adapters/__init__.py:ADAPTERS`. See `adapters/base.py` for the four-method Protocol.

## Troubleshooting

**Daemon log:**
```powershell
# Windows
Get-Content -Wait "$env:LOCALAPPDATA\claude-beacon\Cache\daemon.log"
```
```bash
# macOS / Linux
tail -f ~/.cache/claude-beacon/daemon.log
# (macOS: ~/Library/Caches/claude-beacon/daemon.log)
```

**Daemon stuck:**
```bash
claude-beacon status                          # shows pid
kill $(cat ~/.cache/claude-beacon/daemon.pid)  # POSIX
```
```powershell
Stop-Process -Id (Get-Content "$env:LOCALAPPDATA\claude-beacon\Cache\daemon.pid")
```

**Kasa bulb not found:**
```bash
claude-beacon scan
```
If empty, the bulb is on a different L2/L3 segment (common with mesh routers' guest/IoT networks), or Windows Firewall is blocking the broadcast reply. Use its IP directly in `config.toml`.

**HTTP endpoint not firing:**
- Verify the state is configured in `[[http.endpoints.<state>]]`. By design, unconfigured states are silent.
- Check the daemon log for the HTTP response code. 429 = rate-limited (ntfy free tier ≈ 5/min; Discord webhooks ≈ 5/min).

## License

MIT — see [LICENSE](./LICENSE).

## Acknowledgments

- [python-kasa](https://github.com/python-kasa/python-kasa) — TP-Link Kasa + Tapo client library.
- [ntfy.sh](https://ntfy.sh) — simple HTTP-based pub/sub for push notifications.
