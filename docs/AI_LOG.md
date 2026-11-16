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
