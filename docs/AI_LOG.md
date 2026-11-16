# Agentic AI usage log

## 2026-11-16 - Phase 0 research and project comparison

- Tool/model: Codex desktop assistant; exact model version not exposed in the session. Connected Gmail, web research, PowerShell, and bundled PDF tools were used.
- Goal: read the course assignment and research a distinctive, rigorous, enjoyable project feasible for one student in two weeks.
- Prompt summary: owner requested deep research, supplied reliable-UDP and Lossy-Link Lab ideas, and required following AGENTS.md.
- Produced: docs/RESEARCH.md with three candidates, primary-source references, technical caveats, proposed experiments, demonstration outline, and a provisional schedule. Created a local research branch and a .gitignore that excludes the personal email PDF and temporary files. No application code or committed project selection.
- Human input/review: owner confirmed solo work. No project approval or review of the research findings has been recorded yet.
- Important correction: a TCP application relay cannot emulate native TCP segment loss by discarding already-read bytes. The proposed lab distinguishes stream constraints from UDP datagram impairment and reserves native TCP loss claims for appropriate packet-level evidence.
- Agent mistakes and recovery: the first source-discovery call printed excessive tool metadata; later discovery was targeted. Default Python lacked PDF-reading libraries; the bundled runtime was used without installing packages. pypdf returned empty text for the PDF, and a rendering attempt with fitz failed because it was absent. Bundled Poppler then rendered both pages and they were visually reviewed. The first branch switch reported a permission error and misleading success text; inspecting HEAD showed main, then an approved sandbox escalation successfully created feat/project-research.
- Verification performed: full AGENTS.md read; assignment email/thread read; two PDF pages rendered and inspected; primary technical references reviewed. A Python documentation check passed for file readability, trailing newlines, an explicit not-run disclaimer, absence of a personal mailbox address in the new files, and absence of PROJECT.md. `git check-ignore 'CN - Agentic AI Project.pdf' tmp/pdfs/assignment-1.png` confirmed both private source and temporary render exclusions. `git status --short --branch` confirmed feat/project-research.
- Tests/measurements: application tests, network tests, benchmarks, and Linux checks not run because no implementation exists. Proposed settings and schedules are not results.
- Git verification: `git diff --cached --check` passed. The local documentation commit was attempted but failed because Git has no configured author identity. No identity was invented or global settings changed. Files remain staged on feat/project-research; no commit or merge was made.
- Next gate: owner selects a project; then write docs/PROJECT.md and begin the approved MVP.

## 2026-11-16 - Project definition

- Tool/model: Codex desktop, gpt-6.1-terra; GitHub connector and PowerShell.
- Goal: document the approved FreshLink MVP and prepare repository setup.
- Owner review: approved FreshLink and explicitly excluded custom reliable UDP unless scope changes; authorized GitHub access for this repository.
- Produced: PROJECT.md and DECISIONS.md; updated research status. No transport code was written.
- Mistakes and checks: `gh` is unavailable; the connected GitHub integration independently returned the requested login and numeric ID. Its repository creation capability was not exposed. No author email from the profile was used.
- Tests: application and network tests not run; no implementation exists.

## 2026-11-16 - Repository setup

- Goal: initialize the private repository, research PR, and cross-platform CI.
- The owner authorized the GitHub repository and approved installation of GitHub CLI if necessary. The connected account was verified and a repository-local noreply identity set.
- The initial main commit contains only LICENSE, README.md, .gitignore and AGENTS.md. A content and filename scan preceded the first push; the local email PDF and temporary renders are ignored.
- Mistake and recovery: `git merge --no-commit --no-ff --allow-unrelated-histories main` failed because identical untracked LICENSE and README.md would be overwritten. An isolated index and a two-parent commit joined the histories without rewriting either existing commit or deleting the files.
- CI adds a repository-artifact smoke test; it does not claim transport functionality. Owner review of the new CI is pending.

## 2026-11-16 · Transport core

- Tool and model — Codex desktop, GPT-6.1 Sol, PowerShell, and GitHub.
- Goal and prompt — proceed with Step 4 by implementing the approved TCP and UDP transport core on a feature branch.
- Produced — a versioned snapshot codec, bounded TCP framing, a UDP freshness receiver, a loopback CLI, standard-library tests, and a protocol walkthrough with a real test trace.
- Human review — the owner approved repository setup and requested the transport milestone. Transport code review is pending.
- Mistake and recovery — the first full test invocation used the default sandbox. TCP connect returned WinError 10013 and UDP reads timed out. Running the same tests with loopback access passed, isolating the failure to the execution environment.
- Verification — `python -m unittest discover -s tests -v` passed 11 tests on Windows. Twenty further runs of `python -m unittest discover -s tests -q` passed. CLI sender and receiver subprocesses delivered three samples and exited successfully on each transport, using ephemeral ports. The seeded UDP test recorded loss, duplicate, reordering, and checksum rejection. Benchmarks were not run.

## 2026-11-16 · Impairment relay

- Tool and model — Codex desktop, GPT-6.1 Sol, PowerShell, and GitHub.
- Goal and prompt — the owner approved the transport core and requested a seeded loopback relay, deterministic tests, documentation, and a verified PR before dashboard work.
- Produced — a bounded scheduler and one-way CLI relay with TCP application delay, jitter, and pacing; UDP adds loss, duplication, reordering, and corruption. The walkthrough records an actual loss and reordering trace.
- Human review — the owner approved the previous milestone. Review of this relay is pending.
- Mistake and recovery — the initial Windows TCP test put its client socket into listen mode through a fixture helper, causing WinError 10022. The client now uses a separate non-listening socket and the loopback integration test passes.
- Verification — `python -m unittest discover -s tests -v` passed 17 tests. Twenty Windows reruns with `python -W error::ResourceWarning -m unittest discover -s tests -q` passed. The Windows CLI probe relayed 12 TCP samples and recorded all four UDP faults with seed 17 using ephemeral ports. Both CLI paths exited successfully. No performance benchmarks were run.

## 2026-11-16 · Dashboard telemetry and controls in progress

- Tool and model — Codex desktop and GPT-6.1 Terra.
- Goal — connect the SSE server to shared live telemetry through the existing TCP and UDP relays and add a validated loopback control endpoint.
- Produced — a live source, two receiver metrics, and a relay profile update path. Settings apply to future admissions; queued frames retain their original eligibility. Outage pauses TCP release and drops newly admitted UDP datagrams.
- Human review — the owner requested this bounded step. Review of the implementation remains pending.
- Mistakes and fixes — the initial stale-time fraction divided by time before the first known sample. It now divides by elapsed time since first receipt. A control test initially treated HTTPConnection as a context manager and failed; explicit cleanup fixed it. The first relay wake-up implementation cleared a shared event for both relays; separate events prevent one relay consuming the other's notification. A repeated suite run failed intermittently without captured details; the outage test now allows packets already in flight to settle before checking the receiver counts.
- Verification — `python -m unittest discover -s tests -v` passed 23 tests on Windows with loopback access, including SSE delivery from both relay paths, invalid control rejection, a short outage, recovery, and cleanup. Twenty subsequent full suite runs passed. A separate six-second loopback outage recovered on both paths. Dashboard UI and Linux local execution remain unverified.

## 2026-11-16 · Sender isolation and outage regression

The owner requested independent TCP and UDP sender tasks and a root-cause investigation of the intermittent outage test. The previous failure was discarded by the repeat harness, so its exact exception cannot be recovered. A new harness captured a failure on run 20. Windows logged the intended HTTP 403, then aborted the client connection with WinError 10053 before the status arrived. The handler rejected the origin and closed the socket with an unread POST body. Reading the bounded request body before sending the rejection addressed the reproduced failure. The original failure may have had the same cause.

The old assertion also assumed that the control response formed a receiver delivery barrier. A gated TCP reader now demonstrates that a pre-outage release can be accepted after the endpoint acknowledges the outage. The test observes TCP releases and UDP drops directly, then checks recovery. It does not use a settle delay. Fifty successive outage runs passed after the HTTP fix, with tracebacks and snapshots retained on failure. A separate test held the TCP sender blocked until its source queue overflowed and verified UDP sequence continuity and delivery cadence.

## 2026-11-16 · Dashboard page and launcher

The 24-test Windows suite passed with loopback access, and `node --check web/app.js` passed. The Windows launcher opened the page on an ephemeral port. In the browser, UDP loss increased the relay drop count, an outage made both paths stale, and Healthy restored freshness. Reloading during UDP loss restored the selected preset from the server. The initial metric lists pushed the charts down the page, so the detailed rows now expand on demand. Interrupting the launcher ended the preview process, but the terminal reported exit code 1, so a clean CLI exit status remains unverified.
