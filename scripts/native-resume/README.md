# Native resume compatibility — ARCHIVED / DO NOT USE (2026-09-08)

> **This approach was retired by decision on 2026-09-08 and must not be re-enabled.**
> `proxy/cxp` no longer has an activation branch: it runs exactly one `exec command codex`.
> The gate is `tests/test_resume_routing.py::NoPatchedBinaryEntry`, which fails if the branch,
> the `native-codex` / `CODEX_NATIVE_BIN` tokens, or the binary itself come back.
> Everything below is kept only as a record of what was built and why it was dropped.
>
> **Three independent reasons, any one of which is sufficient:**
>
> 1. **It broke every tool call.** Codex resolves helper executables relative to its own
>    executable's directory, and `build.py` copies only the `codex` binary — the official vendor
>    directory ships four items (`codex`, `codex-code-mode-host`, `codex-resources/`, `codex-path/`).
>    `code_mode_host` is a stable/enabled feature, so a failed spawn makes
>    `codex_core::tools::router` fail closed and the model cannot invoke a single tool.
>    Observed: `failed to spawn code-mode host …/native-codex/codex-code-mode-host: No such file or directory`.
>    **This failure shows no sign of a broken config** — `codex doctor` is all green, `config.toml`
>    parses, auth is fine, all MCP servers are listed — so the obvious first move (inspect the
>    config) wastes a full round. Only a real `codex exec` surfaces the cause.
> 2. **It pins the version.** The patch targets 0.153.4 while npm had already moved to
>    0.154.0-alpha.6. `codex update` upgrades the npm copy while the pinned patch is what runs —
>    silently diverging.
> 3. **Every upstream release requires re-applying, rebuilding and re-verifying the patch.**
>
> Built artifacts were moved to `~/archive/codex-account-rotator/native-codex-dropped-20260908/`.
> The known cost of not having it is documented in `CLAUDE.md` §8: the `rotateproxy` picker lists
> only `rotateproxy`-stamped sessions. `codex resume <session-id>` still opens across providers.

This optional build preserves OpenAI Codex's native picker and resume implementation. For the local `rotateproxy` provider, it discovers both `rotateproxy` and `openai` histories. Other providers keep their original filters. `--all` still controls working-directory scope.

The patch is pinned to upstream `rust-v0.153.4`, commit `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`. Its local version is `0.153.4+codexbar.1`; it is a local build from official source, not an unmodified OpenAI release binary. Upstream upgrades require rebuilding and revalidating this patch. The npm installation remains available for rollback.

History metadata, UUIDs, JSONL headers, and SQLite rows are not migrated by this compatibility layer. Normal native resume/storage updates still occur. Before each local proxy resume, the TUI creates an immutable marker under `CODEX_ROTATE_STORE/.proxy-sessions-v1/<canonical-home-sha256>/<uuid>`. `codex-rotate` uses it to exclude anonymous proxy quota echoes from active-account attribution. Keep the markers after exit; deleting them can reintroduce incorrect quota attribution. This is separate from token attribution through `response_id`.

Build with Python 3.12+, Git, and the Rust toolchain specified by the pinned source. All third-party dependency versions remain locked. The source hash gate refuses unknown or partially patched files. `--debug` is available for a faster local build; omit it for a release profile build. Build output is separate from activation.

```sh
python3 scripts/native-resume/build.py --source scratch/codex-native-resume-0.153.4 --output output/native-codex --debug
```

The default build timeout is 600 seconds. On a timeout, inspect build progress before retrying with the same source directory; Cargo reuses completed work.

Run the repository suite, then the native TUI suite. Native terminal tests need a real terminal type and no inherited `NO_COLOR`; the patch includes reviewed version-specific snapshots for the local build identity.

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

```sh
bash scripts/test-codex-session-visibility.sh
```

```sh
env -u NO_COLOR TERM=xterm-256color CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 just --working-directory scratch/codex-native-resume-0.153.4/codex-rs --justfile scratch/codex-native-resume-0.153.4/justfile test -p codex-tui
```

Exercise the actual native picker in an isolated `CODEX_HOME` with synthetic histories. The POSIX PTY harness compares the upstream picker to the patched picker, checks cwd scope, cancellation, selection, UUID resume, unchanged original headers, and native provenance registration. It sends no model prompt and points the synthetic provider at an unavailable local endpoint.

```sh
python3 scripts/native-resume/verify.py --codex output/native-codex/codex --baseline /absolute/path/to/original/codex --output output/native-resume-proof
```

Activate only after verification: deploy the matching `codex-rotate` and `resume_provenance.py` to both daemon and CodexBar resource locations, restart quotad, then place the verified executable at `<CODEX_ROTATE_STORE>/native-codex/codex`. `proxy/cxp` will select it through the existing guard script while keeping `--profile rotateproxy` and `NO_PROXY`. Without that file, existing users retain their current entry. Caller-supplied `CODEX_HOME` is preserved. The native app-server always closes before a separate CLI resume in the diagnostic tooling; the production picker uses its existing in-process app-server.

Rollback by renaming `native-codex` within the store; `cxp` returns to the original installed CLI. Keep quota markers and the compatible quota reader because mixed historical quota events remain on disk. No history restoration is needed merely to disable the patch.

The Rust patch and build helper support Windows paths and produce `codex.exe`, but this repository's new automatic activation branch is the Bash `cxp` entry. Windows interactive installation and the native PTY proof require separate Windows validation before distributing a Windows integration. Do not change other users' shell profiles or turn on the optional build through an unattended upgrade. No cross-device history synchronization is provided.
