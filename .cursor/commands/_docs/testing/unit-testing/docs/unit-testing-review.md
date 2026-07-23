# Unit Testing Review

Controls HOW the test-review-agent subagent evaluates a generated test suite, HOW findings are categorized, and HOW Category A findings feed back into skill improvements. This file is read by the main generation agent after the subagent returns its report. It is also embedded in the test-review-agent subagent's definition.

The reviewer operates on three inputs only: the code under test, the generated test file(s), and the original requirements or spec if one exists. It does not receive generation reasoning, skill commentary, or the generation agent's context. This isolation is intentional.

**Invoking test-review-agent:** The caller invokes the agent by name (`test-review-agent`) and, in the message, provides paths to or @-mentions of (1) all source files under test, (2) all generated test files from the session, and (3) optionally the requirements or spec. The agent reads those files and returns the structured findings. Do not pass generation reasoning or commentary.

---

## Reviewer Framing

The reviewer's job is adversarial, not confirmatory. The default question is not "does this test suite look reasonable?" It is: **"How could these tests pass while the implementation is broken?"**

Every finding must be grounded in a specific test or a specific gap. Vague observations ("coverage could be better") are not findings. A finding names the test or missing scenario and explains the concrete failure mode.

---

## Finding Categories

Every finding is assigned exactly one category. The category determines what happens next.

### Category A — Skill failure

The generation skill had a rule that should have prevented this issue, and it didn't. The test suite violated an existing rule, or a rule exists that directly addresses this scenario but wasn't applied.

Examples:
- Missing five-part docstring header in a generated test (style rule)
- Exception type in `pytest.raises` doesn't match what the code actually raises (cases rule)
- Test asserts only `mock.called` with no payload or argument verification (cases rule)
- Conditional logic inside a test body (style rule)
- Wrapper method with branching logic has no tests for the alternate branch (cases rule)
- Nullable input (`None`, `""`) not tested separately when code branches on it (cases rule)

**Action:** Fix before delivering the test suite. Log the pattern for skill review.

### Category B — Review advantage

The issue is only visible from outside the generation context. No existing skill rule addresses it, or the issue requires reasoning about the broader codebase, upstream behavior, or domain knowledge that the generation agent didn't have.

Examples:
- A test asserts correct behavior for the current implementation, but the implementation has a latent bug the test doesn't surface
- A mock response is structurally plausible but missing a field the real API always returns, which downstream code branches on
- An edge case that only matters given knowledge of how this code is actually called in production
- A test that would pass even if a critical conditional were removed, because the mock short-circuits the real path

**Action:** Surface to the user with explanation. Do not silently fix. These are informational -- the user decides what to do. Log them separately from Category A.

---

## Review Checklist

Work through these in order. For each item, identify specific tests or gaps -- do not mark "pass" without checking.

### 1. Vacuous tests (highest priority)

A vacuous test passes regardless of whether the implementation is correct.

- Does the test assert only on values it set up itself? (e.g., mock returns `{"id": 1}`, test asserts `result["id"] == 1` -- this proves nothing about the code under test)
- Does the test assert only `mock.called` or `mock.called_once` without verifying call arguments or return values?
- Does the test assert on a constant that would be true no matter what the function returns?
- Could you delete the function body (replace with `pass` or `return None`) and have the test still pass?

### 2. Missing branches

- Identify every conditional in the code under test (if/else, guard clauses, try/except, type-based dispatch).
- For each branch: is there at least one test that exercises it and asserts the correct outcome for that branch specifically?
- For type-based dispatch (employee/contractor/student, 200/4xx/5xx): does each type have a test that verifies the correct payload or behavior, not just that the function ran?

### 3. Exception type mismatches

- For every `pytest.raises(SomeException)` in the test suite: does the code under test actually raise `SomeException`, or does it raise something else that gets caught and re-raised or wrapped?
- If the code does `except ClientError: raise e`, the test must assert `ClientError`, not `Exception`.
- If the code wraps: `raise UserProvisioningException(str(e))`, the test must assert `UserProvisioningException`.
- Check `match=` patterns against the actual message the code constructs.

### 4. Incomplete mock structures

- For every mock response object: which fields does the code under test actually read or branch on?
- Are all of those fields present in the mock?
- A mock missing a field that the code branches on will make the test pass for the wrong reason (the branch never fires).

### 5. Nullable and boundary gaps

- Does the code branch on `None` vs `""` vs populated? Are all three tested separately?
- Does the code read from dicts or JSON where upstream might send the literal string `"null"`? Is that tested?
- For collection inputs: are empty, one-item, and many-item cases all covered where the code behaves differently across them?

### 6. Error path gaps

- For every method that makes an HTTP call or invokes an external client: are 4xx and 5xx cases tested?
- Does each error path test assert on the specific exception type and message pattern the handler raises, not a generic `Exception`?
- For boto3 clients: is `ClientError` specifically tested where the code can raise it?

### 7. Wrapper and payload coverage

- For every public method that builds a payload: is the payload shape asserted, not just that the client was called?
- For methods with branching payload logic: is each branch's payload shape verified in a separate test or parameterized case?
- Does a test exist that calls the wrapper's public method (not a private helper) and asserts on the client call arguments?

### 8. State transition completeness

- For methods that change state: is the transition case tested (inactive → active)?
- Is the no-op case tested (already active → no update called)?

### 9. Style and structure

- Does every test have all five docstring headers: Behavior, Scenario/inputs, Expected outcome, Why this case, Justification?
- Does every test use Arrange-Act-Assert with section comments?
- Does any test contain conditionals, loops, or computation? If so, that's a Category A failure.
- Does the naming follow `test_MethodUnderTest_Scenario_ExpectedBehavior`?

### 10. Assert-implementation alignment

- For infra or snapshot tests: do resource counts match the actual construct? Are magic numbers explained?
- For any assertion using a hardcoded value: is it derivable from the code under test, or is it an assumption that could silently drift?

---

## Output Format

Return findings in this structure. Do not summarize or editorialize beyond what the format asks for.

```
## Category A Findings (fix before delivery)

[finding number]. [Test name or "Missing test for [scenario]"]
- Issue: [one sentence describing the problem]
- Rule violated: [which rule in which skill file]
- Fix: [specific correction]

## Category B Findings (surface to user)

[finding number]. [Test name or "Missing scenario: [description]"]
- Issue: [one sentence describing the problem]
- Why only visible in review: [one sentence]
- Suggested action: [what the user might consider]

## Summary

- Category A count: [n]
- Category B count: [n]
- Tests reviewed: [n]
- Checklist items with no findings: [list]
```

If there are no findings in a category, say "None." Do not omit the section.

---

## Feedback Loop: Updating the Skill

This section is for the main generation agent, not the review subagent.

After receiving the reviewer's report:

1. **Fix all Category A findings** in the generated test suite before delivering to the user.

2. **Log Category A findings** with their associated rule. A single occurrence is a data point. A pattern across multiple generation runs is a signal that the rule needs strengthening.

3. **Update skill rules when a Category A pattern recurs.** The threshold is two or more occurrences of the same type of failure across separate generation runs. One-offs are noise; recurring failures indicate a rule gap.

4. **Distinguish rule gap from rule ignored.** If the rule exists and was ignored, the fix may be adding an example or making the rule more concrete. If the rule doesn't cover the scenario, add it. If the rule exists but is too abstract to be actionable, rewrite it with a specific test pattern.

5. **Consolidate when adding rules.** Before adding a new rule, check whether it supersedes or generalizes an existing one. Prefer one precise rule over two overlapping rules. Periodically (every 10-15 generation sessions), review the skill files for rules that can be merged or removed.

6. **Do not add rules for Category B findings.** Category B findings are inherent to the review advantage -- they require context the generation agent doesn't have. Trying to push them upstream produces rules that are too broad to be useful and adds bloat.
