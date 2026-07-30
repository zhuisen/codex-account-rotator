#!/usr/bin/env python3
"""codex-rotate quota daemon — keeps state.json's quota continuously accurate, INDEPENDENT of any UI
(SwiftBar / CodexBar). Two complementary loops, both ZERO quota cost:

  1. rollout tail (every TICK_SECS)  — `quota --save` attributes the newest plain-codex rollout's
     rate_limit event to the ACTIVE account. Local file read, instant, but only covers the active
     account and only when plain codex actually wrote a rollout.

  2. usage API   (every USAGE_SECS) — `refresh-all` reads Codex's OFFICIAL account-usage endpoint
     (GET /backend-api/codex/usage) for EVERY account. Authoritative, live, covers non-active accounts,
     and 401 identifies revoked tokens.

★ Why loop 2 exists: rollouts are an unreliable telemetry source. Usage driven through the cxp proxy,
through resumed sessions, or through wrappers may not produce a fresh readable plain rollout at all —
observed the newest rollout being 25h stale while the account had really moved 39% → 64%. The displayed
quota then silently lagged reality. The usage endpoint removes that dependency entirely.

★ Why polling is affordable now: the old probe sent a real (billed) `POST /codex/responses` just to read
quota headers, so automatic refresh had to be disabled once Codex retired the 5h window for a small
weekly one. The official endpoint is a plain GET — it costs no quota and no tokens, so we can poll it.
"""
import contextlib
import importlib.machinery
import io
import sys
import time

ROT = "/Users/you/Projects/tools/codex-account-rotator/codex-rotate"
cli = importlib.machinery.SourceFileLoader("cli", ROT).load_module()

TICK_SECS = 15    # rollout tail (local file read)
USAGE_SECS = 180  # official usage API for the whole pool — GET, zero quota; modest polling rate


def tick_rollout():
    # hold the cross-process state mutex for the whole load→attribute→save, exactly as the CLI's main()
    # does for STATE_LOCKED commands — calling cmd_quota directly would otherwise bypass that lock and
    # could race the proxy. Swallow cmd_quota's stdout (it prints the quota JSON).
    with cli._state_mutex():
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_quota(["--save"])


def tick_usage():
    """Refresh EVERY account from the official usage endpoint. cmd_refresh_all does its own targeted
    _mutate_state per account (it must not hold the state mutex across network I/O)."""
    with contextlib.redirect_stdout(io.StringIO()):
        cli.cmd_refresh_all([])


def main():
    sys.stderr.write(f"[quotad] started · rollout={TICK_SECS}s · usage-api={USAGE_SECS}s (GET, zero quota)\n")
    sys.stderr.flush()
    last_usage = 0.0
    while True:
        try:
            tick_rollout()
        except Exception as e:
            sys.stderr.write(f"[quotad] rollout err: {e}\n")
            sys.stderr.flush()
        now = time.time()
        if now - last_usage >= USAGE_SECS:
            last_usage = now
            try:
                tick_usage()
            except Exception as e:
                sys.stderr.write(f"[quotad] usage err: {e}\n")
                sys.stderr.flush()
        time.sleep(TICK_SECS)


if __name__ == "__main__":
    main()
