# GA-01C Controlled Merge Gate Policy and Execution Checklist

Status: **PROPOSED / NOT APPLIED / MERGE NOT AUTHORIZED**
Date: 2026-10-10
Scope: experimental GA-01C stack only; no production permission grant.

## 1. Pinned candidate and immutable evidence

- Initial main: `661b95d2ba06d0db7e7c39ebe635efe901d770b3`
- Stack (each PR targets the preceding branch):
  - #96 `fe23b0b2ef02ec029d1b67d08e5ab8a8356adfb4`
  - #97 `4404ccf6dda6a28359219cfdec3700c94562f1ea`
  - #98 `f7854a95f4fd72e4de3c8f815c6188fa8424c738`
  - #99 `646d1d2372bf03c8df3ddf02fa0ffe5cae5d73e0`
  - #100 `c182d1cb82ed066191e0f5b77b9c67c0743c13e4`
  - #101 `430a179fd8d5511414a3aea59702354b087efd43`
  - #102 `889908fb9d909ae3c8b819a27f78614bb016607e`
  - #103 `f960eed2c16c94aa28126296ca426e63f0e1d132`
  - #104 `4985d29949289f60e312fe4a84ce2bd871a364f5`
- Recorded initial main→#104 compare: ahead 59, behind 0, changed 32 files.
- Final baseline engineering: Actions [38030833638](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38030833638), 1249 passed / 7 skipped, mypy 263 files, Ruff check/format PASS.
- Final actual-model integration: Actions [38030833645](https://github.com/cxjchelsea/AgentRuntime/actions/runs/38030833645), 3×(12/12 completed, 18/18 correct); one rejected nonblank-strategy violation recovered by exactly one **pre-execution** retry. No claim of statistical model reliability or production recovery.
- Previous failed real-model evidence must be retained and labeled **FAILED**, not made green:
  #98 run 38018592251 (EVAL-02), #99 run 38020116913 (DIAG-01), #101 run 38025342955 (DIAG-03), #103 run 38029748170 (three-trial reliability). Standard engineering jobs in those runs succeeded.

## 2. Gate definitions and non-bypass rules

**Mandatory engineering gate for the exact integration candidate:** full pytest, mypy, Ruff lint/format, with the workflow's actual conclusion SUCCESS; adverse M4 legality, identity, source-bound, cancellation and malformed-response cases must remain enabled.

**Mandatory actual-model gate for the exact final candidate:** run the GA-01C Final Integration Gate including real Ollama smoke, Loop, no-answer-leak case, and all three DIAG-03 repeats; **each** repeat must meet its frozen test assertions; failed attempts remain counted, cannot be averaged away, retried away by CI rerun, or downgraded to informational after the fact. Record actual PR HEAD versus Actions synthetic merge checkout SHA and model/container digests. Experimental bounded invalid-choice reinference is opt-in only, max one, before execution, while original M4 legality still independently controls final choice.

**Historical diagnostic evidence:** retain original red Jobs in #98/#99/#101/#103. They are not counted as a passing final-candidate test. They may be included as an experimental historical evidence package *only by explicit owner approval and only if all actually enforced branch rules/required checks allow the chosen merge procedure*. Never disable or falsify checks, change acceptance thresholds, force-merge through admin bypass, or erase failure logs solely to obtain green status.

**Scope guard:** accepted GA-01C integration is experimental sandbox only. It does not grant production StateStore trust, Tool execution/side effects, M6 Positive Grant, Runtime default retry, statistical model reliability, or domain-independent Agent completion.

## 3. GitHub settings verification — BLOCKING FACT NOT YET VERIFIED

The current connector can read repository's `allow_merge_commit=true` and Admin permission, plus PR `mergeable=true`, but **cannot establish active branch protection, org/repo rulesets, required named checks, review count or bypass restrictions**.

Before any merge action, an authorized repository owner must inspect the effective settings at GitHub repository **Settings → Rules → Rulesets** and **Settings → Branches**, including rules targeting `main` and patterns affecting the intermediate base branches. Record the exact required named checks, required review decisions, whether Draft is prohibited (GitHub normally blocks it), required linear history/merge queue and who is allowed to bypass. If an enforced rule conflicts with sequential standard merge commits, STOP and prepare a separately authorized compliant path rather than bypassing it.

The empty legacy Commit Status API response is not evidence that GitHub Checks or required rules are absent.

## 4. Controlled sequential merge protocol

**Not authorized by this document.** Proposed mechanism only: exact-head **standard merge commits**, strict order #96→#104; no squash, rebase, auto-merge or forced update. Each PR requires its own fresh authorization/eligibility check. Do not merge the whole stack from one stale green review.

For step `#N`:
1. Record exact `main` HEAD, `#N` HEAD/base HEAD, Draft state, required reviews/checks, `mergeable`, outstanding discussions, and the exact expected incremental diff before action.
2. After prior PR's merge, inspect `#N` base. Retargeting to `main` (if necessary) is a distinct reviewable operation and must not be assumed automatic; verify a correct merge base, no ancestor reapplication, and run new exact-head checks. A changed base may alter PR diff and CI.
3. Convert Draft→Ready and obtain required approvals only when owner authorizes; do not accept the owner's authorizing their own review as satisfying GitHub's independent-review policy if the platform disallows it.
4. If a historic live Job remains required/red or a required review/rule blocks merging, **STOP**. Do not use admin bypass. Escalate to an owner-approved alternative (e.g., a clean-main cumulative integration PR whose exact CI and diffs are reviewed), while preserving all earlier PRs and evidence.
5. If and only if all required rules and explicit owner authorization are satisfied, merge using **standard merge commit** for precisely one PR.
6. Refresh `main` exact SHA and run/check standard post-merge integration; repeat from step 1 for next PR. Halt for SHA drift, missing changed files, unexpected duplicate patch, altered accepted semantics, or unverified model gate.

## 5. Final exact-main acceptance (after all authorized merges)

- Verify the final main diff versus the pinned initial main covers the intended 32 original files **plus any separately authorized governance documents** and no unexpected files.
- Execute full pytest, mypy, Ruff check and Ruff format for the actual final main commit.
- The `.github/workflows/ga01c-final-integration.yml` live job runs on PR events and supports `workflow_dispatch`; its live Job does **not** run automatically on ordinary main push. Verify this workflow exists on main, explicitly dispatch it on `main`, then confirm **the checked-out SHA is the exact final main HEAD** (not a PR merge ref), all three real-model trials complete, and failure propagation and model digests are recorded.
- Do not grant production permissions. Keep historical red evidence and model reliability limitation on the release note.
- A final accepted main run is needed; a successful prior PR synthetic-merge run alone is insufficient.

## 6. Authorization state / next decision

- **Stack topology**: VERIFIED at pinned refs.
- **Final candidate engineering/live**: VERIFIED WITH SANDBOX LIMITATIONS.
- **Active GitHub rule settings**: NOT VERIFIED; merge blocker.
- **Nine Draft PRs**: OPEN; must not be directly merged.
- **Merge execution**: NOT AUTHORIZED.
- **Policy in this document**: PROPOSED. Owner sign-off is required before it is treated as governing merge policy.

Next review: capture exact GitHub Rules/Branches settings, select compliant integration route, then conduct per-PR **Exact-Main Merge Execution Authorization**, separately from this preparation.
