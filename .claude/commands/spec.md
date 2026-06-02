---
description: Write a feature spec to docs/specs/<feature>.md, then stop for review. No code until the spec is approved.
argument-hint: <feature>
---

Write a specification for **$ARGUMENTS** to `docs/specs/$ARGUMENTS.md`, then **stop and wait
for my review**. Do not enter Plan Mode and do not write any code until I approve the spec.

The spec must contain these sections:

1. **Objective** — what this feature proves, in one paragraph; which milestone it belongs to
   and what it builds on.
2. **Scope** — explicitly in scope / out of scope (deferred). Build only what proves the
   current milestone (CLAUDE.md).
3. **Files** — every file to create or edit, as a tree, with a one-line purpose each.
4. **Data-model touchpoints** — which schemas/tables/enums from `docs/data-model.md` this
   feature reads or writes; any new migration (one migration per schema-changing milestone).
5. **API touchpoints** — endpoints added/changed, matching `docs/api-spec.md`.
6. **Tests** — the test list (names + what each asserts). TDD on trust-critical code:
   metrics, rules, tools get tests/fixtures first.
7. **Acceptance criteria** — measurable, matching the milestone's acceptance in
   `docs/IMPLEMENTATION-PLAN.md`.
8. **Principles compliance** — a table mapping each of the 10 principles in
   `docs/principles.md` to how this feature honors it (or N/A and why).
9. **Open questions** — decisions the owner must make before implementation.

Keep it tight and concrete — file names, function names, payload shapes. No prose padding.
