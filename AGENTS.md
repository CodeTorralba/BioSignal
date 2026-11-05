## Approach

Less is more. Don't overengineer. The simplest solution that works is usually the best one.

## Code changes

- Read the relevant code and reuse existing logic and project conventions.
- Make the smallest complete change that solves the root cause while preserving required behavior. If fixing the root cause needs a larger change, explain why before making it.
- Prefer straightforward code. Add modules, abstractions, configuration, or dependencies only for a concrete current need.
- Do not use placeholders or fake data as working functionality unless requested. Mocks and fixtures are allowed in tests.
- Document non-obvious decisions, constraints, and public contracts. Avoid comments that repeat the code; follow required project documentation standards.
- For Python, use `uv` and the project's existing environment and dependency files. Use `uv add` to add dependencies and `uv run` to run commands. Do not use `pip` directly.

## Tests and validation

- Run relevant existing checks and any mandatory project checks.
- Add or update tests only to cover meaningful behavior or a plausible regression that existing tests miss. Test observable results, not internal structure.
- For bug fixes, prefer a test that fails before the fix and passes after it. Avoid duplicate coverage and tests for formatting-only changes.
- Do not delete, skip, or weaken existing tests to make checks pass.
- Expand testing only to address a specific remaining risk. Stop once the change is adequately verified and required checks pass. Report checks you could not run.

## Workflow

- Read supporting documentation when its topic is relevant to the task.
- Make routine decisions within scope. Ask when ambiguity materially affects the result.
- Ask before pushing code, deploying, or taking destructive actions unless already authorized. Routine, reversible local edits and checks within scope do not require confirmation. Never print or commit secrets.
- Complete the requested implementation and verification. Leave optional improvements for a separate task. Mention unrelated issues you notice, but do not fix them.

## Git and commits

- For implementation tasks, create local commits after completing the work and required verification, unless asked to leave changes uncommitted.
- Check existing changes before editing. Before committing, review the staged diff and include only task-related changes. Preserve unrelated work from the user or other agents.
- Follow the repository's commit-message conventions. Otherwise, use a short, specific description of the change. Explain why when it is not obvious.
- Do not rewrite shared history or amend another contributor's commits without explicit authorization.
- Do NOT co-author the commit

## Communication style

When you write messages to me:

- Use simple, clear English. Assume I am not a software expert.
- Use short sentences and common words.
- Avoid idioms, slang, and unusual expressions.
- When you use a technical term, explain it briefly the first time.
- Be direct: say what you did, what the result is (including anything that failed or that you are unsure about), and what you need from me.

This guidance applies to communication only. Use plain language without sacrificing technical accuracy or implementation quality.