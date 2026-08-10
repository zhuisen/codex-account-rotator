#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
wrapper="${script_dir}/codex-wrapper-with-logout-guard.sh"
fixture_home="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/codex-resume-repair-test.XXXXXX")"

cleanup() {
  if [ -d "$fixture_home" ]; then
    /usr/bin/find "$fixture_home" -depth -delete
  fi
}
trap cleanup EXIT

/bin/mkdir -p \
  "$fixture_home/.codex" \
  "$fixture_home/.local/npm-global/bin" \
  "$fixture_home/tmp"
/bin/cp /usr/bin/true "$fixture_home/.local/npm-global/bin/codex"

/usr/bin/sqlite3 "$fixture_home/.codex/state_5.sqlite" <<'SQL'
CREATE TABLE threads (
  id TEXT PRIMARY KEY,
  has_user_event INTEGER NOT NULL,
  model_provider TEXT NOT NULL,
  archived INTEGER NOT NULL,
  thread_source TEXT,
  source TEXT NOT NULL,
  first_user_message TEXT NOT NULL
);
INSERT INTO threads VALUES
('11111111-1111-1111-1111-111111111111',0,'rotateproxy',0,'user','cli','human'),
('22222222-2222-2222-2222-222222222222',0,'rotateproxy',0,NULL,'cli','legacy human'),
('33333333-3333-3333-3333-333333333333',0,'rotateproxy',0,'user','exec','history-backed exec'),
('44444444-4444-4444-4444-444444444444',0,'rotateproxy',0,'user','exec','one shot'),
('55555555-5555-5555-5555-555555555555',0,'rotateproxy',0,NULL,'{"subagent":"reviewer"}','subagent'),
('66666666-6666-6666-6666-666666666666',0,'rotateproxy',1,'user','cli','archived'),
('77777777-7777-7777-7777-777777777777',0,'rotateproxy',0,'user','cli',''),
('88888888-8888-8888-8888-888888888888',0,'rotateproxy',0,'user','cli','');
SQL

history="$fixture_home/.codex/history.jsonl"
/opt/homebrew/bin/jq -nc '{session_id:"11111111-1111-1111-1111-111111111111",text:"do not overwrite"}' > "$history"
/opt/homebrew/bin/jq -nc '{session_id:"22222222-2222-2222-2222-222222222222",text:"legacy human"}' >> "$history"
/opt/homebrew/bin/jq -nc '{session_id:"33333333-3333-3333-3333-333333333333",text:"history-backed exec"}' >> "$history"
/opt/homebrew/bin/jq -nc '{session_id:"55555555-5555-5555-5555-555555555555",text:"subagent"}' >> "$history"
/opt/homebrew/bin/jq -nc '{session_id:"66666666-6666-6666-6666-666666666666",text:"archived"}' >> "$history"
/opt/homebrew/bin/jq -nc '{session_id:"77777777-7777-7777-7777-777777777777",text:"restored title"}' >> "$history"
/usr/bin/printf '%s\n' '{"session_id":' >> "$history"

HOME="$fixture_home" TMPDIR="$fixture_home/tmp" "$wrapper" resume --help
HOME="$fixture_home" TMPDIR="$fixture_home/tmp" "$wrapper" resume --help

actual="$(/usr/bin/sqlite3 -separator '|' "$fixture_home/.codex/state_5.sqlite" \
  'SELECT id,has_user_event,model_provider,first_user_message FROM threads ORDER BY id;')"
expected='11111111-1111-1111-1111-111111111111|1|openai|human
22222222-2222-2222-2222-222222222222|1|openai|legacy human
33333333-3333-3333-3333-333333333333|1|openai|history-backed exec
44444444-4444-4444-4444-444444444444|0|rotateproxy|one shot
55555555-5555-5555-5555-555555555555|0|rotateproxy|subagent
66666666-6666-6666-6666-666666666666|0|rotateproxy|archived
77777777-7777-7777-7777-777777777777|0|rotateproxy|
88888888-8888-8888-8888-888888888888|0|rotateproxy|'

if [ "$actual" != "$expected" ]; then
  /usr/bin/printf '%s\n' 'session visibility regression failed' >&2
  /usr/bin/printf '%s\n' "$actual" >&2
  exit 1
fi

if /usr/bin/find "$fixture_home/tmp" -maxdepth 1 -name 'codex-human-sessions.*' -print -quit | /usr/bin/grep -q .; then
  /usr/bin/printf '%s\n' 'temporary session ID file was not removed' >&2
  exit 1
fi

/usr/bin/printf '%s\n' 'codex session visibility regression: PASS'
