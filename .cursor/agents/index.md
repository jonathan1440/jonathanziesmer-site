# INDEX — `.cursor/agents`

Task subagents for parallel review (`consider-reviewing`, `/gh-review`). Full definitions in each file.

| Agent | Path |
| --- | --- |
| gh-build | [gh-build.md](gh-build.md) — Composer worker for `/gh-build` |
| gh-resolve-issues | [gh-resolve-issues.md](gh-resolve-issues.md) — Composer worker for `/gh-resolve-issues` |
| code-reviewer | [code-reviewer.md](code-reviewer.md) |
| database-reviewer | [database-reviewer.md](database-reviewer.md) |
| flutter-reviewer | [flutter-reviewer.md](flutter-reviewer.md) |
| go-reviewer | [go-reviewer.md](go-reviewer.md) |
| healthcare-reviewer | [healthcare-reviewer.md](healthcare-reviewer.md) |
| java-reviewer | [java-reviewer.md](java-reviewer.md) |
| kotlin-reviewer | [kotlin-reviewer.md](kotlin-reviewer.md) |
| python-reviewer | [python-reviewer.md](python-reviewer.md) |
| rust-reviewer | [rust-reviewer.md](rust-reviewer.md) |
| security-reviewer | [security-reviewer.md](security-reviewer.md) |
| test-review-agent | [test-review-agent.md](test-review-agent.md) |
| typescript-reviewer | [typescript-reviewer.md](typescript-reviewer.md) |

Descriptions live in each file's YAML frontmatter (`description:`). Applicability rules: [../commands/gh/procedures/lib/consider-reviewing.md](../commands/gh/procedures/lib/consider-reviewing.md).
