#!/usr/bin/env python3
"""Build a pinned optional CodexBar native CLI; Python 3.12+, Rust, Git required."""
import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import signal
import subprocess
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMIT = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
VERSION = "0.153.4+codexbar.1"


def prepare(source):
    if not source.exists():
        url = f"https://codeload.github.com/openai/codex/tar.gz/{COMMIT}"
        with urllib.request.urlopen(url, timeout=60) as response:
            archive = response.read(50_000_000)
        source.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="codex-source-", dir=source.parent) as staging:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
                prefix = bundle.getmembers()[0].name.split("/")[0]
                bundle.extractall(staging, filter="data")
            (Path(staging) / prefix).rename(source)
    manifest = json.loads((HERE / "source-hashes.json").read_text())
    states = []
    for name, hashes in manifest.items():
        path = source / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        if digest == hashes["patched"]:
            states.append("patched")
        elif digest == hashes["upstream"]:
            states.append("upstream")
        else:
            raise RuntimeError(f"Source differs from the pinned version: {name}")
    if len(set(states)) != 1:
        raise RuntimeError("Partially patched source; use a fresh source directory")
    if states[0] == "upstream":
        # Isolate git apply from any parent repository when using a release tarball.
        if not (source / ".git").exists():
            subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "apply", "--check", str(HERE / "codex-0.153.4.patch")], cwd=source, check=True)
        subprocess.run(["git", "apply", str(HERE / "codex-0.153.4.patch")], cwd=source, check=True)
    root = source / "codex-rs"
    cargo = root / "Cargo.toml"
    cargo.write_text(cargo.read_text().replace('version = "0.153.4"', f'version = "{VERSION}"', 1))
    lock = root / "Cargo.lock"
    # The upstream release tag leaves workspace lock entries at 0.0.0. Keep all
    # third-party versions and checksums intact while stamping local build identity.
    blocks = lock.read_text().split("[[package]]")
    for i, block in enumerate(blocks[1:], 1):
        package = tomllib.loads(block)
        if "source" not in package and package.get("version") in ("0.0.0", "0.153.4"):
            blocks[i] = block.replace(f'version = "{package["version"]}"', f'version = "{VERSION}"', 1)
    lock.write_text("[[package]]".join(blocks))
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--debug", action="store_true", help="Faster local build; release is the default")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    root = prepare(source)
    command = ["cargo", "build", "--locked", "-p", "codex-cli", "--bin", "codex"]
    if not args.debug:
        command.append("--release")
    env = dict(os.environ, CARGO_BUILD_JOBS=str(args.jobs), CARGO_PROFILE_DEV_DEBUG="0")
    process = subprocess.Popen(command, cwd=root, env=env, start_new_session=True)
    try:
        result = process.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
        raise
    if result:
        raise subprocess.CalledProcessError(result, command)
    name = "codex.exe" if os.name == "nt" else "codex"
    binary = root / "target" / ("debug" if args.debug else "release") / name
    version = subprocess.check_output([str(binary), "--version"], text=True).strip()
    if VERSION not in version:
        raise RuntimeError(f"Wrong build identity: {version}")
    output.mkdir(parents=True, exist_ok=True)
    staged = output / (name + ".tmp")
    shutil.copy2(binary, staged)
    os.replace(staged, output / name)
    identity = {"upstream_commit": COMMIT, "version": VERSION, "platform": platform.platform(),
                "profile": "debug" if args.debug else "release",
                "sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
                "patch_sha256": hashlib.sha256((HERE / "codex-0.153.4.patch").read_bytes()).hexdigest()}
    (output / "build.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(json.dumps(identity, indent=2))


if __name__ == "__main__":
    main()
