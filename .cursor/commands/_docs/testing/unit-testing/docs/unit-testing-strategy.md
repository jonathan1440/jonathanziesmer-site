# Unit Testing Strategy

Decides WHETHER to test, WHAT KIND of test to write, and at what PRIORITY. Run this first. Its outputs feed into the cases and style guidelines.

## CRITICAL RULES (never violate)

1. **ALWAYS run the prioritization decision tree before writing tests.** State which branch applies and why.
2. **When creating or expanding a test suite, consider every module in the package.** For each module, apply Decision Tree 1. If the decision is "skip" (e.g. trivial), document it in a short docstring or a single smoke test. Do not leave a module entirely untested without an explicit skip decision.
3. **ALWAYS quarantine flaky tests immediately.** Do not leave flaky tests in the main suite.
4. **Achieve complete module coverage.** Every module in the package should have at least one test file. Trivial modules can have a single smoke test; non-trivial modules require comprehensive coverage per Decision Tree 1.

---

## Pre-questions (ask before proposing any test plan)

Ask the user once per session or feature, cache the answers, and reuse them when applying the decision trees. Fall back to conservative defaults (treat as higher risk / higher priority) when the user cannot answer.

1. **Roadmap / lifecycle** — Is this code scheduled for replacement within 3 months?
2. **Current change scope** — Am I (or are we) about to modify this code as part of the current work?
3. **Operational history and risk** — Has this code caused bugs or incidents recently? Is this core business logic, payment processing, or security-related? Is this code changed frequently OR touched by multiple developers?
4. **Product and domain importance** — Is this a critical user journey?
5. **Testing strategy and cost** — Does this have a large input space where enumeration is impractical? Is this dependency slow (e.g. typical call >10ms in production)?

These questions are a hard prerequisite. Do not propose a test plan or any concrete test edits before asking and recording answers to all five.

---

## Decision Tree 1: Should I write tests for this code?

Execute this tree before writing any test. State your reasoning.

```
INPUT: Code unit to potentially test

1. Is this code's contract (public API, input parameters, return output, behavior guarantees) going to change in the relative near future?
   YES → SKIP. State: "Skipping tests: contract scheduled to change; tests would be invalidated."
   NO  → Continue to 2.
   Note: If implementation will change but contract stays the same, test anyway.

2. Is this code trivial?
   Definition of trivial: No branches, pure delegation (forwards inputs unchanged without constructing payloads), simple getter/setter.
   Exception: Exception classes that are part of the public API or used by other code get at least ONE smoke test (subclass of expected base, raise/catch, message preserved). Trivial = one smoke test max; for exception types, maximum is one, not zero.
   YES → SKIP or write ONE smoke test maximum. State: "Trivial code: [reason]."
   NO  → Continue to 3.

3. Am I about to modify this code?
   YES → Write CHARACTERIZATION TESTS before modifying. See Legacy Code section below.
   NO  → Continue to 4.

4. Has this code caused bugs or incidents recently?
   YES → HIGH PRIORITY. Test failure scenarios first. State: "Bug history: testing [scenarios]."
   NO  → Continue to 5.

5. Is this core business logic, payment processing, or security-related?
   YES → HIGH PRIORITY. Test thoroughly: multiple scenarios, edge cases, error paths.
   NO  → Continue to 6.

6. Is this code changed frequently OR touched by multiple developers?
   YES → MEDIUM PRIORITY. Test the public API.
   NO  → LOW PRIORITY. Test if time permits. State: "Low priority: stable, single-owner code."
```

## Decision Tree 2: What kind of test should I write?

```
INPUT: Code unit that needs tests (from Decision Tree 1)

1. Is this pure logic with no external dependencies?
   YES → UNIT TEST. Fast, isolated, deterministic.
   NO  → Continue to 2.

2. Does this test interaction between components I control?
   YES → INTEGRATION TEST or sociable unit test with real collaborators.
   NO  → Continue to 3.

3. Does this test a boundary with external systems (DB, API, file system)?
   YES → INTEGRATION TEST with test doubles at the boundary. Consider CONTRACT TESTS if external system has defined schema.
   NO  → Continue to 4.

4. Is this a critical user journey?
   YES → E2E TEST. Use sparingly. High maintenance cost.
   NO  → Continue to 5.

5. Does this have a large input space where enumeration is impractical?
   YES → Consider PROPERTY-BASED TESTING.
   NO  → Default to UNIT TEST.
```

## Decision Tree 4: Test is hard to write. What do I do?

```
INPUT: Difficulty writing test for code unit

1. Is the difficulty due to many dependencies?
   YES → Find SEAMS: constructor injection, parameter injection, extract-and-override, config flags, wrap-and-delegate. Apply and retry.
   NO  → Continue to 2.

2. Is a branch unreachable from the public API?
   YES → First, try different inputs/scenarios through public API. Still unreachable?
        → Is this dead code? YES → REMOVE the code. Do not test dead code.
        → Not dead code? → Extract to testable unit with public interface.
        → Last resort: test private method directly. Document this coupling.
   NO  → Continue to 3.

3. Is the difficulty due to global state?
   YES → Refactor to inject state, OR reset global state in setup/teardown.
   NO  → Continue to 4.

4. Is I/O mixed with logic?
   YES → EXTRACT pure logic into functions that accept data as parameters. Test the pure logic. Integration test the I/O boundary.
   NO  → Continue to 5.

5. Is the testing cost disproportionate to the value?
   YES → SKIP. Document: "Skipping: [reason]. Revisit if [condition]."
   NO  → Revisit steps 1-4; you missed something.
```

## Decision Tree 5: Flaky test detected. What do I do?

```
INPUT: Test that fails intermittently

IMMEDIATE ACTION: Quarantine the test. Move to separate suite or mark skip.
Do not leave flaky tests in main suite.

THEN diagnose root cause:

1. Timing assumptions (sleeps, timeouts, race conditions)?
   → FIX: Use explicit waits, events, or polling with timeout. Never use sleep().

2. Shared mutable state between tests?
   → FIX: Isolate test data. Reset state in setup/teardown. Each test independent.

3. Test order dependency?
   → FIX: Each test must pass when run alone. Fix setup or split tests.

4. Real external calls (network, database)?
   → FIX: Mock or fake the external dependency.

5. Time or date dependency?
   → FIX: Inject a controllable time provider.

6. Root cause unclear or fix expensive?
   → DELETE the test. A flaky test has negative value.
```

---

## Legacy Code Rules

### Characterization tests

Purpose: Capture current behavior as safety net before refactoring.

Procedure:
1. Call the code with representative inputs.
2. Assert against what the code ACTUALLY returns, not what you think it should return.
3. Repeat for edge cases.
4. Expect tests to pass immediately. If they fail, your assertion is wrong.

### Document surprising behavior

When behavior is wrong, surprising, or likely to be "fixed" by a future refactor, document in the test docstring:

```python
def test_GetValue_LiteralNullString_ReturnsStringNull():
    """
    Current behavior: literal string "null" from upstream is returned as-is.
    This is intentional; normalization happens downstream in [location].
    Do not change to return None without updating downstream consumers.
    """
    result = get_value({"key": "null"})
    assert result == "null"  # String, not None
```

### Test at the change boundary

1. Identify code you will modify.
2. Write characterization tests for current behavior.
3. Make your changes.
4. Tests should pass unless you intentionally changed behavior.
5. Update tests only for intentional behavior changes.

---

## Strategy Checklist

Before moving to the cases or style rules:

1. **Run prioritization** — Execute Decision Tree 1. State: "Testing [code unit] because [reason from tree]. Priority: [high/medium/low]."
2. **Identify test type** — Execute Decision Tree 2. State: "Writing [unit/integration/e2e] test because [reason]."
3. **Pass context forward** — Cache for cases and style: pre-question answers, priority level, test type, whether this is legacy/characterization testing.

---

## FIRST Principles

- **Fast:** Milliseconds per test. No sleeps, no real network, no shared mutable state.
- **Independent:** No shared state, no order dependence. Each test must pass when run alone.
- **Repeatable:** Same result every run, any environment.
- **Self-validating:** Pass/fail from assertions only.
- **Timely:** Written when code is written.

## Test Design Principles

- **No Real I/O:** Mock external API clients, HTTP calls, database connections, file system. Use test doubles. Assert on return values, payloads, call arguments.
- **Determinism and Speed:** No sleeps or timing dependencies, no real network, no shared mutable state. Tests run in milliseconds and are repeatable.
