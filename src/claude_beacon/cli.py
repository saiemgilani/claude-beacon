"""click-based CLI. Subcommands:
    hook <state>   - Claude Code hook entrypoint
    daemon         - run the long-lived state machine
    scan           - discover devices (per-adapter; impl in Tasks 9, 11)
    status         - show daemon liveness and config path
    setup          - interactive config wizard (impl in Tasks 9, 11)
"""

from __future__ import annotations

import sys

import click

from . import hook as hook_mod
from . import runtime_paths as rp
from .state import State


@click.group()
@click.version_option()
def main() -> None:
    """claude-beacon: status indicator daemon for Claude Code."""


@main.command()
@click.argument("state",
                type=click.Choice([s.value for s in State], case_sensitive=False))
def hook(state: str) -> None:
    """Hook entrypoint: write desired state, spawn daemon if needed.
    Always exits 0 so Claude Code is never blocked."""
    try:
        hook_mod.write_state_atomic(rp.STATE_FILE, state)
        if not hook_mod.daemon_alive(rp.PID_FILE):
            hook_mod.spawn_daemon_detached(
                log_file=rp.LOG_FILE,
                pid_file=rp.PID_FILE,
            )
    except Exception as e:
        # Never propagate to Claude Code; just log to the log file.
        try:
            rp.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(rp.LOG_FILE, "ab") as f:
                f.write(f"hook error: {e}\n".encode("utf-8"))
        except Exception:
            pass
    sys.exit(0)


@main.command()
def daemon() -> None:
    """Run the daemon: load config, instantiate adapter, loop."""
    import asyncio
    import os
    import signal

    from .adapters import ADAPTERS
    from .config import load_config
    from .daemon import run_state_machine
    from .state import LockHeldError, acquire_lock

    if not rp.CONFIG_FILE.exists():
        click.echo(f"no config at {rp.CONFIG_FILE}; run `claude-beacon setup` first",
                   err=True)
        sys.exit(2)

    cfg = load_config(rp.CONFIG_FILE)
    adapter_cls = ADAPTERS.get(cfg.adapter)
    if adapter_cls is None:
        click.echo(f"unknown adapter {cfg.adapter!r}", err=True)
        sys.exit(2)

    # Single-instance lock.
    rp.ensure_dirs()
    lock_fp = open(rp.LOCK_FILE, "w")
    try:
        acquire_lock(lock_fp)
    except LockHeldError:
        click.echo("another daemon is already running", err=True)
        sys.exit(0)

    rp.PID_FILE.write_text(str(os.getpid()))

    async def _run() -> None:
        adapter_kwargs = getattr(cfg, cfg.adapter)
        adapter = adapter_cls(adapter_kwargs)
        try:
            await adapter.connect()
        except Exception as e:
            click.echo(f"connect failed: {e}", err=True)
            sys.exit(1)

        shutdown = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                asyncio.get_running_loop().add_signal_handler(sig, shutdown.set)
            except (NotImplementedError, ValueError):
                # Windows lacks signal handlers in asyncio.
                pass

        try:
            await run_state_machine(adapter, rp.STATE_FILE, cfg.daemon,
                                      shutdown=shutdown)
        finally:
            try:
                await adapter.apply_state(State.OFF)
            except Exception:
                pass
            await adapter.close()
            try:
                rp.PID_FILE.unlink()
            except FileNotFoundError:
                pass

    try:
        asyncio.run(_run())
    finally:
        lock_fp.close()


@main.command()
def scan() -> None:
    """Discover devices on the local network (Kasa-only - HTTP doesn't scan)."""
    import asyncio
    from .setup_kasa import discover_or_manual

    devs = asyncio.run(discover_or_manual())
    if not devs:
        click.echo("No Kasa/Tapo devices found on the local subnet.")
        click.echo("(Devices on isolated IoT VLANs won't appear; enter their IP")
        click.echo(" manually in `claude-beacon setup`.)")
        return
    for d in devs:
        click.echo(f"  {d['host']:15} {d['alias']!r:25} model={d['model']}")


@main.command()
def status() -> None:
    """Report daemon state, config path, last log lines."""
    click.echo(f"config: {rp.CONFIG_FILE}")
    click.echo(f"pid file: {rp.PID_FILE}")
    if hook_mod.daemon_alive(rp.PID_FILE):
        pid = rp.PID_FILE.read_text().strip()
        click.echo(f"daemon: running (pid {pid})")
    else:
        click.echo("daemon: not running")


@main.command()
@click.option("--adapter", "adapter_choice", type=click.Choice(["kasa", "http"]),
              help="Adapter to configure (interactive prompt if omitted)")
def setup(adapter_choice: str | None) -> None:
    """Interactive config wizard."""
    import asyncio

    if adapter_choice is None:
        adapter_choice = click.prompt(
            "Which adapter? [kasa/http]",
            type=click.Choice(["kasa", "http"]),
            default="kasa",
        )

    if adapter_choice == "kasa":
        asyncio.run(_setup_kasa())
    elif adapter_choice == "http":
        asyncio.run(_setup_http())


async def _setup_kasa() -> None:
    from .setup_kasa import (
        build_kasa_config_text, discover_or_manual, test_connect,
    )

    click.echo("\n[1/4] Discovering Kasa/Tapo bulbs on your local subnet...")
    devs = await discover_or_manual()
    if devs:
        click.echo(f"      Found {len(devs)}:")
        for i, d in enumerate(devs, 1):
            click.echo(f"        [{i}] {d['host']:15} {d['alias']!r} ({d['model']})")
    else:
        click.echo("      (No devices found; you can enter the IP manually.)")

    host = click.prompt("\n      Bulb IP address", type=str)
    hosts = [host]
    if click.confirm("      Add another bulb?", default=False):
        while True:
            extra = click.prompt("      Next IP (or empty to stop)",
                                  default="", show_default=False)
            if not extra:
                break
            hosts.append(extra)

    click.echo("\n[2/4] Is this Kasa (no account) or Tapo (needs TP-Link account)?")
    kind = click.prompt("      [k] Kasa / [t] Tapo", type=click.Choice(["k", "t"]),
                         default="t")
    username = password = None
    if kind == "t":
        username = click.prompt("      TP-Link email", type=str)
        password = click.prompt("      TP-Link password", hide_input=True, type=str)

    click.echo(f"\n[3/4] Connecting to {hosts[0]}...")
    ok = await test_connect(hosts[0], username, password)
    if not ok:
        click.echo("      Connection failed. Check IP and credentials.", err=True)
        sys.exit(1)
    click.echo("      Connected.")

    rp.ensure_dirs()
    rp.CONFIG_FILE.write_text(
        build_kasa_config_text(hosts=hosts, username=username, password=password),
        encoding="utf-8",
    )
    if sys.platform != "win32":
        rp.CONFIG_FILE.chmod(0o600)
    click.echo(f"\n[4/4] Config written to {rp.CONFIG_FILE}")
    click.echo("\nNext: merge settings.example.json into your Claude Code settings,")
    click.echo("       then restart Claude Code.")


async def _setup_http() -> None:
    import httpx
    from .setup_http import (
        build_http_config_text, generate_ntfy_channel, ntfy_endpoint,
    )

    click.echo("\n[1/4] Which notification platform?")
    click.echo("      [n] ntfy.sh        (free, no account, random-name privacy)")
    click.echo("      [d] Discord        (webhook URL from server settings)")
    click.echo("      [s] Slack          (incoming webhook URL)")
    click.echo("      [h] Home Assistant (webhook URL)")
    click.echo("      [c] Custom         (paste a URL and body)")
    choice = click.prompt("      Choose",
                            type=click.Choice(["n", "d", "s", "h", "c"]),
                            default="n")

    endpoints: dict = {}

    if choice == "n":
        channel = generate_ntfy_channel()
        click.echo(f"\n[2/4] Generated channel: {channel}")
        click.echo(f"      Subscribe at https://ntfy.sh/{channel}")
        click.echo("      (Keep the URL private - anyone with it can read your alerts.)")
        click.echo("\n[3/4] Which states should send notifications?")
        click.echo("      [I] input - Claude needs you  (RECOMMENDED)")
        click.echo("      [F] off   - session ended     (RECOMMENDED)")
        click.echo("      [W] working                   (typically too noisy)")
        click.echo("      [D] idle                      (typically too noisy)")
        states = click.prompt("      Comma-separated", default="I,F", type=str)
        chosen = {c.strip().upper() for c in states.split(",") if c.strip()}
        if "I" in chosen:
            endpoints["input"] = [ntfy_endpoint(channel,
                                                  state_label="needs your input",
                                                  priority="high",
                                                  tags="warning,bell")]
        if "F" in chosen:
            endpoints["off"] = [ntfy_endpoint(channel,
                                                state_label="session ended",
                                                priority="low",
                                                tags="white_check_mark")]
        if "W" in chosen:
            endpoints["working"] = [ntfy_endpoint(channel,
                                                    state_label="working",
                                                    priority="low",
                                                    tags="hourglass_flowing_sand")]
        if "D" in chosen:
            endpoints["idle"] = [ntfy_endpoint(channel,
                                                 state_label="idle",
                                                 priority="low",
                                                 tags="zzz")]
    else:
        # For Discord / Slack / HA / Custom: prompt URL + body per state.
        click.echo("\n[2/4] Enter webhook URL:")
        url = click.prompt("      URL", type=str)
        click.echo("\n[3/4] We'll configure INPUT only by default.")
        body = click.prompt(
            "      JSON body (or empty for none)",
            default='{"text": "Claude needs your input"}', show_default=True,
            type=str,
        )
        headers = {"Content-Type": "application/json"} if body else None
        endpoints["input"] = [{
            "url": url, "method": "POST",
            "body": body or None, "headers": headers,
        }]

    # Test fire one notification.
    click.echo("\n[4/4] Sending a real test request to the first INPUT endpoint...")
    first = endpoints.get("input", [None])[0]
    if first is not None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.request(
                    first["method"], first["url"],
                    headers=first.get("headers"),
                    content=first["body"].encode("utf-8") if first.get("body") else None,
                )
            click.echo(f"      Status: HTTP {resp.status_code}")
        except Exception as e:
            click.echo(f"      Test request failed: {e}", err=True)
            if not click.confirm("      Save config anyway?", default=False):
                sys.exit(1)

    rp.ensure_dirs()
    rp.CONFIG_FILE.write_text(
        build_http_config_text(endpoints=endpoints),
        encoding="utf-8",
    )
    if sys.platform != "win32":
        rp.CONFIG_FILE.chmod(0o600)
    click.echo(f"\n      Config written to {rp.CONFIG_FILE}")
    click.echo("\nNext: merge settings.example.json into your Claude Code settings,")
    click.echo("       then restart Claude Code.")
