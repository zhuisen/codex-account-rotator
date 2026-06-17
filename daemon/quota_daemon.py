#!/usr/bin/env python3
"""codex-rotate quota daemon — keeps state.json's ACTIVE-account quota continuously accurate from the
newest plain-codex rollout's rate_limit event, INDEPENDENT of any UI (SwiftBar / CodexBar). cxp traffic
is already metered live per-request by proxy.py.

Why a daemon: accuracy used to ride on the SwiftBar plugin's 10s `quota --save` tick. Once SwiftBar
retires (the native CodexBar app only READS state.json), nothing would refresh the active account. This
daemon owns that job: every INTERVAL it runs codex-rotate's own locked `quota --save` (same attribution
+ cross-process .state.lock as the CLI), so the displayed quota stays fresh no matter which UI is up.

Passive — it tails rollouts, it does NOT probe, so it costs zero quota. Non-active accounts stay on the
daily 07:00 refreshquota probe (+ the manual refresh-all button)."""
import contextlib
import importlib.machinery
import io
import sys
import time

ROT = "/Users/you/Projects/tools/codex-account-rotator/codex-rotate"
cli = importlib.machinery.SourceFileLoader("cli", ROT).load_module()
INTERVAL = 15  # seconds


def tick():
    # hold the cross-process state mutex for the whole load→attribute→save, exactly as the CLI's main()
    # does for STATE_LOCKED commands — calling cmd_quota directly would otherwise bypass that lock and
    # could race the proxy. Swallow cmd_quota's stdout (it prints the quota JSON).
    with cli._state_mutex():
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_quota(["--save"])


def main():
    sys.stderr.write(f"[quotad] started · interval={INTERVAL}s · tails plain rollouts → active account\n")
    sys.stderr.flush()
    while True:
        try:
            tick()
        except Exception as e:
            sys.stderr.write(f"[quotad] err: {e}\n")
            sys.stderr.flush()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
