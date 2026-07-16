#!/usr/bin/env bash
# ONE-TIME: create a stable self-signed code-signing identity "CodexBar Self-Signed"
# so TCC grants (Accessibility / Notifications) SURVIVE rebuilds.
# Ad-hoc signing ("-") gives a new code identity every build → macOS forgets grants.
#
# Run in YOUR shell:  ! bash ~/Projects/tools/codex-account-rotator/codexbar/scripts/setup-signing.sh
#
# Idempotent: re-run any time to re-sign the current build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IDENTITY="CodexBar Self-Signed"
BUNDLE_ID="com.doushutangmu.codexbar"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
APP="/Applications/CodexBar.app"
CERTDIR="$ROOT/scratch/signing"
OPENSSL="/usr/bin/openssl"
mkdir -p "$CERTDIR"

if security find-identity -p codesigning | grep -q "$IDENTITY"; then
    echo "==> identity '$IDENTITY' already in keychain — skipping creation"
else
    echo "==> creating self-signed code-signing cert '$IDENTITY'"
    TMP="$(mktemp -d)"
    cat > "$TMP/openssl.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = $IDENTITY
[v3]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF
    "$OPENSSL" req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -keyout "$TMP/key.pem" -out "$TMP/cert.pem" -config "$TMP/openssl.cnf"
    "$OPENSSL" pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
        -name "$IDENTITY" -out "$CERTDIR/codexbar.p12" -passout pass:codexbar
    security import "$CERTDIR/codexbar.p12" -k "$KEYCHAIN" -P codexbar -T /usr/bin/codesign -A
    rm -rf "$TMP"

    echo "==> authorizing codesign to use the key (needs your macOS login/keychain password)"
    read -rsp "macOS login (keychain) password: " PW; echo
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$PW" "$KEYCHAIN" >/dev/null
    unset PW
    echo "    p12 backup: $CERTDIR/codexbar.p12  (pass: codexbar)"
fi

if [ -d "$APP" ]; then
    echo "==> re-signing $APP with '$IDENTITY'"
    codesign --force --deep --sign "$IDENTITY" "$APP"
    codesign --verify --strict "$APP"
    echo
    echo "DONE. Now relaunch CodexBar — grants persist across future rebuilds."
    codesign -dvv "$APP" 2>&1 | grep -E "Authority|Signature" | head -2
else
    echo "!! $APP not found — build first: cd codexbar && npx tauri build --bundles app"
fi
