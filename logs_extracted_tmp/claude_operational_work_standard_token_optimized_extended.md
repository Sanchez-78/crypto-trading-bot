# Claude — Token-Optimized Work Standard + Project Structure

Goal: maximize correctness, minimize risk, minimize token waste.

## Priority Order
When rules conflict, use:
1. Correctness
2. Safety
3. Reversibility
4. Simplicity
5. Performance
6. Elegance

## Plan Mode
Use plan mode only if the task:
- has 3+ dependent steps
- changes architecture, interfaces, or shared behavior
- affects production logic
- touches multiple files/layers
- has non-trivial regression risk

Skip formal planning for trivial, isolated, reversible edits.

## Minimal Plan Format
Before implementation, define:
- objective
- constraints
- files/components touched
- risks
- validation method
- done criteria

If assumptions break, stop and re-plan.

## Scope Rules
- make the smallest safe change
- touch only necessary files
- avoid unrelated refactors
- preserve existing behavior unless change is intentional
- state key assumptions briefly

## Delegation Rules
Use subagents/parallel work only for:
- research
- codebase search
- isolated debugging
- option comparison

Rules:
- one task per subagent
- define expected output first
- merge centrally
- resolve contradictions before coding
- main path owns final correctness

## Validation Rules
Never mark done without evidence.

Acceptable proof:
- tests
- reproducible manual check
- logs
- before/after behavior
- sample input/output

For risky changes also check:
- edge cases
- regression risk
- rollback path
- observability

Ask:
- does it work?
- how do I know?
- what fails first if wrong?

## Bug Fixing
Process:
1. identify symptom
2. find root cause
3. verify cause with evidence
4. apply minimal safe fix
5. confirm resolution

Do not stop at symptom suppression unless temporary mitigation is explicitly required.

## Elegance Rule
Ask for non-trivial changes:
- simpler?
- safer?
- easier to maintain?

Prefer elegance only if it does not reduce clarity, safety, or confidence.
Do not over-engineer simple fixes.

## Progress Tracking
Maintain `tasks/todo.md` with:
- objective
- assumptions
- steps
- status
- blockers
- validation notes
- result summary

Update during work, not only at the end.

## Lessons
After corrections, save only reusable lessons to `tasks/lessons.md`:
- pattern
- root cause
- prevention rule
- early warning sign

Do not store one-off trivia.

## Definition of Done
Done means:
- implementation complete
- validation exists
- scope stayed controlled
- risks understood
- results documented

“Probably works” is not done.

## Core Rules
- correctness over cleverness
- proof over confidence
- root cause over patching
- minimal safe change over broad edits
- clarity over verbosity

## Closeout Checklist
- objective clear
- scope minimal
- no unrelated refactor
- root cause verified
- fix validated
- regression/rollback considered
- results documented
- reusable lesson captured if needed

---

## Recommended Project Structure

Use this as a practical default, not a rigid requirement.

```text
my_project/
├─ CLAUDE.md
├─ .claude/
│  ├─ settings.json
│  ├─ settings.local.json
│  └─ commands/
│     ├─ review.md
│     ├─ deploy.md
│     ├─ test-all.md
│     └─ bootstrap.md
├─ skills/
│  ├─ code-review/
│  │  ├─ SKILL.md
│  │  ├─ scripts/
│  │  ├─ references/
│  │  └─ assets/
│  ├─ test-writer/
│  │  └─ SKILL.md
│  └─ security-audit/
│     └─ SKILL.md
├─ agents/
│  ├─ code-reviewer.yml
│  ├─ test-writer.yml
│  └─ security-auditor.yml
├─ src/
├─ tests/
├─ docs/
├─ scripts/
└─ README.md
```

## What Each Part Is For

### `CLAUDE.md`
Use as the project-level operating file:
- project overview
- architecture summary
- conventions and style rules
- testing rules
- safety/security constraints
- branch/workflow notes
- important commands
- repo-specific warnings

Keep it short, high-signal, and maintained.

### `.claude/commands/`
Store reusable slash-command style prompts such as:
- `/review` — review current diff
- `/deploy` — deployment checklist or staging flow
- `/test-all` — full validation workflow
- `/bootstrap` — scaffold a new module or feature
- `/document` — generate docs from implementation

Only keep commands that are reused often.

### `skills/`
Use for repeatable workflows that should behave consistently.

Recommended skill layout:
```text
skill-name/
├─ SKILL.md
├─ scripts/
├─ references/
└─ assets/
```

Guidelines:
- `SKILL.md` = instructions, triggers, boundaries
- `scripts/` = automation helpers
- `references/` = docs/examples loaded when needed
- `assets/` = templates/static resources

Create a skill only when the same workflow repeats enough to justify standardization.

### `agents/`
Use only if you intentionally split work into specialized roles.

Examples:
- code reviewer
- test writer
- security auditor
- docs generator

Each agent should have one clear responsibility.

---

## CLAUDE.md Essentials

A good `CLAUDE.md` should contain:

1. project purpose
2. architecture overview
3. coding conventions
4. testing expectations
5. deployment constraints
6. security rules
7. debugging/logging expectations
8. high-risk areas
9. repo-specific commands
10. definition of done for this repo

Avoid long essays. Prefer short operational rules.

---

## Optional Advanced Extensions

Use only if they clearly improve the workflow.

### Hooks
Potential lifecycle hooks:
- before tool use
- after file writes
- session start
- session end
- pre-commit checks
- notifications

Use hooks for:
- validation gates
- secret scanning
- auto-formatting
- session summaries
- alerting on failures

Do not add hooks unless they save real time or reduce real risk.

### MCP / External Tools
Use external tool integrations only when needed:
- GitHub / PR workflows
- issue trackers
- Slack / notifications
- databases
- browser automation

Rule: minimum permissions, minimum scope, explicit purpose.

### Subagents / Agent Teams
Useful patterns:
- orchestrator
- sequential pipeline
- parallel compare-and-merge
- supervisor / retry loop

Use these only for larger workflows. Avoid complexity for simple tasks.

---

## Context Management

Keep context disciplined.

Rules:
- keep instruction files concise
- avoid duplicating docs into prompts
- link or reference instead of copy-paste
- summarize long sessions
- compact or refresh context before it becomes noisy
- keep project memory higher signal than chat history

Practical rule:
- short and current beats long and forgotten

---

## Security Rules

- never store secrets in `CLAUDE.md`
- use `.env.example` for templates
- keep local secret files gitignored
- run secret scanning before commit when possible
- grant external tools minimum permissions
- do not embed tokens, keys, or credentials in reusable prompts or skills

---

## Anti-Patterns

Avoid:
- huge instruction files with weak signal
- vague prompts like “write good code”
- copying docs into prompts instead of linking or summarizing
- broad refactors during unrelated fixes
- marking tasks done without proof
- skills for one-off tasks
- too many agents for a small problem
- automation without rollback thinking
- hiding uncertainty when evidence is weak

---

## Build a Skill When

Create a skill when:
- you have written the same instructions 3+ times
- the workflow is repeatable
- consistency matters
- the process benefits from templates, scripts, or references
- you want less prompting and more reliable execution

Do not create a skill for ad hoc requests.

---

## Best Working Stack

Use this default model:

- **Prompt** for the immediate task
- **Project context** for repo-specific memory
- **Skills** for repeatable workflows
- **Commands** for reusable task entry points
- **Agents** only when specialization or parallelism helps

This is usually better than relying on any one layer alone.
