use std::process::Command;

/// Build metadata `B` in `X.Y.Z+B` — **derived from git, never hand-maintained**.
///
/// Semantics (decided by the user 2026-09-15, canonical text in `CLAUDE.md` §3.7):
///
/// ```text
///   B == 0  ->  displayed as  vX.Y.Z    "what you run IS the release"
///   B  > 0  ->  displayed as  vX.Y.Z+B  "locally modified since the release, not published"
/// ```
///
/// `B` = number of commits since the most recent tag, `+1` if the working tree is dirty.
/// Right after a release the tree sits exactly on the tag, so `B` is 0 and the local build
/// reports the same version as the published artifact — which is the whole point.
///
/// ## Why derive it instead of keeping a counter file
///
/// The counter version (2026-09-15, lived one day) bumped `B` inside `deploy.sh` *before*
/// building. That made a locally built release artifact report `v1.6.0+1` seconds after the
/// tag was pushed — the user asked exactly the right question: "I just released, why is the
/// local build +1, what changed?" Nothing had changed. The counter could not distinguish
/// "one build past the release" from "the release itself", because it had no notion of the
/// release at all. Git does.
///
/// A derived value also cannot drift: there is no file to forget to reset, and no rule for
/// a future session to violate. This repo's standing lesson is that a written rule without a
/// gate gets broken — so the fix is to remove the rule, not to write it down more firmly.
///
/// ## Failure mode is deliberately quiet
///
/// No git, no tags, or a shallow clone (`actions/checkout` defaults to depth 1) -> `B = 0`.
/// That is the correct answer for a CI build of a tagged release, which is the only case that
/// matters here. It is never *wrong* in a way that misleads: 0 claims "this is the release",
/// and a CI build from the tag is exactly that.
fn build_number() -> String {
    let git = |args: &[&str]| -> Option<String> {
        let out = Command::new("git").args(args).output().ok()?;
        if !out.status.success() {
            return None;
        }
        Some(String::from_utf8_lossy(&out.stdout).trim().to_string())
    };

    let Some(tag) = git(&["describe", "--tags", "--abbrev=0"]) else {
        return "0".into();
    };
    let mut n: u32 = git(&["rev-list", "--count", &format!("{}..HEAD", tag)])
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    // A dirty tree is "locally modified since the release" just as much as a commit is —
    // and it is the state the user is actually in while iterating. Counting it keeps the
    // promise that `vX.Y.Z` with no suffix means "byte-for-byte the released build".
    if git(&["status", "--porcelain"]).is_some_and(|s| !s.is_empty()) {
        n += 1;
    }
    n.to_string()
}

fn main() {
    // Recompute when HEAD moves or a ref changes; otherwise cargo would cache a stale number
    // and the binary would report a build that no longer matches the tree.
    println!("cargo:rerun-if-changed=../../.git/HEAD");
    println!("cargo:rerun-if-changed=../../.git/refs");
    println!("cargo:rustc-env=CODEXBAR_BUILD={}", build_number());
    tauri_build::build()
}
