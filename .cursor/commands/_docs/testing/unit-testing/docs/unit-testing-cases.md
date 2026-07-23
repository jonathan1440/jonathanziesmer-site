# Unit Testing Cases

Decides WHAT SCENARIOS to test, HOW to mock, and what EDGE CASES to cover. This rule assumes the strategy rule has already run and produced a priority level, test type, and cached pre-question answers.

**Decision Tree 3 (mocking) lives in this file. Decision Trees 1, 2, 4, and 5 are in [unit-testing-strategy.md](unit-testing-strategy.md).**

## CRITICAL RULES (never violate)

1. **NEVER skip wrapper/API method coverage.** Every public method that builds payloads, calls external APIs, or has branching logic requires tests. Test payload shape, call arguments, and error handling. Trivial methods (pure delegation with no payload construction, simple getters/setters) can be skipped per Decision Tree 1 in the strategy rule.
2. **NEVER write tests with logic.** No conditionals, loops, or computation in test code. Split into separate tests or use parameterization.

---

## Decision Tree 3: What should I mock?

Execute for each dependency of the code under test. State your decision for each.

```
INPUT: Dependency used by code under test

0. Does my test depend on side effects of this dependency (state changes, writes, enqueued jobs, or other observable effects)?
   YES → Do NOT mock this dependency. Mock at a lower level if needed (for example, mock the slow disk or network call that it uses, not the high-level function whose effects you assert on).
   NO  → Continue to 1.

1. Is this dependency external (network, database, file system, third-party API)?
   YES → MOCK or FAKE. Tests must not depend on external availability.
   NO  → Continue to 2.

2. Is this dependency time or randomness?
   YES → INJECT and CONTROL. Stub time providers, seed random generators.
   NO  → Continue to 3.

3. Is this dependency slow (>10ms)?
   YES → MOCK for unit tests. Real implementation acceptable for integration tests.
   NO  → Continue to 4.

4. Is this an internal class/module that is fast and deterministic?
   YES → USE REAL implementation.
        Exception: Mock if setup is complex AND collaborator has its own test coverage.
   NO  → Continue to 5.

5. Am I mocking so much that the test doesn't resemble real execution?
   YES → STOP. Write an integration test instead, or refactor the code under test.
   NO  → Proceed with current mocking strategy.
```

---

## Coverage Requirements

### Priority order (test in this order)

1. **Business logic outcomes**: Each distinct outcome (approved/rejected, employee/contractor, success/failure) requires at least one test asserting that specific outcome.

2. **Error handling and failure paths**: Test behavior when dependencies fail, inputs are invalid, operations timeout. These are under-tested and where bugs hide.

3. **Branching logic**: Each meaningful branch (if/else, switch, guard clause) must be exercised by at least one test. For methods with type-based branching (e.g., employee vs contractor vs student), ensure each branch is covered with a test that asserts the correct payload or behavior for that type.

4. **Boundary conditions**: Empty vs populated collections, null vs present values, zero/positive/negative numbers, min/max values.

5. **Input validation**: Valid inputs, malformed inputs (missing keys, wrong types), adversarial inputs for security-sensitive code.

6. **Serialization boundaries**: For JSON/similar with specific key shapes (camelCase, snake_case), assert encoded keys and critical values. Roundtrip tests may not catch encoder-only regressions. For types that serialize to JSON (or similar) with a specific key shape, include at least one test that asserts encoder output keys and, where applicable, round-trip or decoder output.

   **Serialization test patterns:**
   - **Encoder output**: Assert on the actual keys and structure produced (e.g., `assert "firstName" in json_output`)
   - **Decoder mapping**: Assert that input keys map to correct object attributes
   - **Missing keys**: Test decoder behavior when optional keys are absent (should use defaults or empty strings)
   - **Round-trip**: Test that encode → decode preserves data (but this alone may not catch encoder-only bugs)
   - **Multiple records**: For batch operations, test both single-record and multi-record cases

7. **State transitions**: For methods that change state (e.g., reactivate inactive user, disable active account), test both the transition case (state changes) and the no-op case (already in target state).

### Nullable value handling (IMPORTANT)

When code branches on null vs empty string vs populated value:

| Input | Test required? | Notes |
|-------|---------------|-------|
| `None` / `null` | YES | Test that code handles absence. Assert on both return value AND whether the key is present in output (e.g., for payload builders, check if key is omitted vs set to null). |
| Empty string `""` | YES | Test that code treats empty string correctly |
| Populated value | YES | Test happy path |
| Literal string `"null"` | YES if code reads from dicts/JSON | Upstream systems often send literal "null" strings. Test that code returns/propagates as-is unless contract specifies normalization. |

Write separate tests for each case with inputs that unambiguously hit that branch. Document surprising behavior in test docstring.

**Example pattern**: For a method that builds API parameters from user data where `email=None` should omit the email key entirely (not send `email: null`), write tests for:
- `email` is `None` → assert `"email" not in params`
- `email` is `""` → assert `params["email"] == ""`
- `email` is populated → assert `params["email"] == expected_value`

### Wrapper/API method coverage (MANDATORY)

For any class/module that wraps an external API:

1. LIST every public method that builds a payload or has branching logic.
2. For EACH non-trivial method, verify tests exist for:
   - Payload shape (correct keys, optional keys omitted when appropriate)
   - Call arguments passed to underlying client
   - Error handling (4xx, 5xx, empty responses, exceptions)
   - For each dependency that can raise (e.g. boto3 `ClientError`, `requests` HTTP errors), at least one test where that dependency raises **its real exception type**. Assert that the wrapper propagates or wraps it as the code specifies (same type re-raised, or wrapped message).
3. Do NOT skip thin-looking methods if they construct requests or have branching logic.
4. Prefer tests that call **public** wrapper methods and assert on client calls and payloads. Testing only private or name-mangled helpers is not sufficient for "method covered"; it does not verify the wrapper's actual contract.
5. For methods that delegate to a per-type or per-branch helper (e.g. a method that selects a generator by account type), ensure public tests cover the main branches by calling the public method and asserting the client was invoked with the correct payload for each branch. One public test that only checks "client was called" is not sufficient when the method has multiple payload shapes.
6. **Explicit wrapper initialization test**: If the wrapper class has non-trivial initialization (e.g., fetching secrets, parsing configuration, constructing clients with region/credentials), write at least one test that verifies the initialization logic (secret parsing, client construction with correct parameters, region handling).

Example of a method that looks thin but requires tests:
```python
def reactivate_user(self, user_id: int) -> dict:
    return self.client.update_user(user_id, status=1)
```
This requires tests: Does it pass correct status? What if client raises? What if user already active?

### Exception coverage

If the codebase has exception classes that are part of the public API or used by other code, ensure each has at least one smoke test (subclass of expected base, raise/catch, message preserved).

### Assertion–implementation consistency

When testing error paths:

- **Exception type:** If the code catches and re-raises (e.g. `raise e`), the test must assert that same type (e.g. `ClientError`), not a generic `Exception`, unless the code explicitly wraps it.
- **Exception message:** Use `pytest.raises(..., match=...)` with a pattern that matches the actual message the code raises (including wrapper messages like `"Error processing record.\\n..."`).
- **Infra/snapshot tests:** Expected resource counts (e.g. `resource_count_is("AWS::Lambda::Function", N)`) must be verified against the stack or module under test. Prefer deriving N from the code or documenting the source (e.g. "4 Lambdas per stack definition"); avoid unexplained magic numbers.

### Initialization and Default Values

For classes with initialization logic or default values:

**Test patterns:**
- **Default initialization**: Test that creating an object with no arguments produces correct defaults (e.g., empty strings, None values, default collections)
- **Full initialization**: Test that creating an object with all fields populated correctly assigns all attributes
- **Partial initialization**: Test that optional fields can be omitted and defaults are used

**Example:**
```python
def test_UsernameDetails_DefaultInit_AllFieldsEmpty():
    """Test that default initialization produces empty strings for all fields."""
    details = UsernameDetails()
    assert details.first_name == ""
    assert details.last_name == ""
    assert details.email == ""

def test_UsernameDetails_FullInit_AllFieldsSet():
    """Test that all fields can be set via initialization."""
    details = UsernameDetails(
        first_name="Alice",
        last_name="Smith",
        email="alice@example.com"
    )
    assert details.first_name == "Alice"
    assert details.last_name == "Smith"
    assert details.email == "alice@example.com"
```

### Utility Method Coverage

For utility methods that extract or transform data:

**Test patterns:**
- **Value present**: Method returns the value when key exists
- **Value absent**: Method returns default/empty when key doesn't exist
- **Key present with None value**: Method handles `key: None` correctly (may differ from absent key)

**Example:**
```python
def test_GetNonNullValue_KeyPresent_ReturnsValue():
    """Test extraction when key exists with value."""
    result = get_non_null_value({"name": "Alice"}, "name")
    assert result == "Alice"

def test_GetNonNullValue_KeyAbsent_ReturnsEmptyString():
    """Test extraction when key doesn't exist."""
    result = get_non_null_value({}, "name")
    assert result == ""

def test_GetNonNullValue_KeyPresentWithNone_ReturnsEmptyString():
    """Test extraction when key exists but value is None."""
    result = get_non_null_value({"name": None}, "name")
    assert result == ""
```

### What to skip

- Trivial getters/setters with no logic
- Pure delegation that forwards inputs unchanged without payload construction
- Generated code from trusted generators
- Unreachable code paths (but consider removing unreachable code)

---

## Edge Case Checklist

Apply when planning test cases. Check each category against the code under test. **Apply the checklist for each input or branch that affects behavior** (event payload keys, query params, response fields, config), not only once per module.

| Category | Cases to test |
|----------|---------------|
| **Collections** | Empty `[]`, one item `[x]`, many items `[x,y,z]`, `None` vs empty `[]` |
| **Nullable** | Value present, `None`, empty string `""`, literal `"null"` (for dict/JSON readers). For collections returned from external APIs, also test when the API returns `None` vs empty list. |
| **Numeric** | Zero, positive, negative, min value, max value, boundary values |
| **Strings** | Empty, whitespace-only, very long, special characters, unicode |
| **External responses** | Success, empty result, `None`, error response, exception, timeout |
| **State** | Valid transition, invalid transition, idempotent operation (already in target state) |
| **Boolean/existence checks** | Item exists → True, item doesn't exist → False, edge cases (e.g., same user vs different user, None vs empty) |
| **Event/payload shapes** | Missing top-level key, missing nested key, empty list (e.g. `Records: []`), key present but `None`, wrong type (e.g. string where list is expected) |

---

## Test Doubles Reference

| Type | Purpose | When to use |
|------|---------|-------------|
| **Stub** | Provides canned responses | Dependency must return specific values for test to run |
| **Mock** | Verifies interactions | Must assert code called dependency in specific way |
| **Fake** | Working non-production impl | Need realistic behavior (e.g., in-memory database) |
| **Spy** | Records calls for verification | Need to verify interactions without replacing behavior |

Use precise terminology. Do not call everything a "mock."

### Mocking SDK Types

When mocking objects from external SDKs or libraries, use `Mock(spec=ActualType)` to ensure test doubles match the real SDK type. This catches attribute errors and provides better test fidelity.

Example:
```python
from unittest.mock import Mock
from external_sdk import DeviceType

# Good: spec ensures mock has same interface as real type
mock_device = Mock(spec=DeviceType)

# Bad: no spec, can call any attribute without error
mock_device = Mock()
```

---

## Mocking Anti-Patterns (NEVER violate)

### Anti-Pattern 1: Testing mock behavior

WRONG:
```python
def test_renders_sidebar():
    # Asserts the mock exists, not that real behavior works
    assert mock_sidebar.called
    assert "sidebar-mock" in rendered_output
```

RIGHT: Test real behavior. Either:
- Render the real component and assert on what a user or caller actually sees, or
- If you must mock for isolation, assert on the behavior of the code that uses the mock (e.g., correct payload or side effect), not just that "the mock was called."

**Gate:** Before asserting on any mock, ask: "Am I testing real behavior or just that the mock exists?" If it's the latter, delete or rewrite the assertion.

### Anti-Pattern 2: Incomplete mocks

WRONG:
```python
mock_response = {"status": "success", "data": {"id": 123}}
# Missing metadata field that downstream code accesses
```

RIGHT: Mock the structure that actually exists in reality. At minimum:
- Include all fields that your code reads, branches on, or depends on.
- Include at least one "irrelevant" field so you don't accidentally assume a minimal schema.

If you don't know the real structure, check the real API/docs or a real example response before mocking.

**Gate:** Before creating mock responses, ask: "Which fields does our code read or branch on in the real response?" Include all of those, plus a representative extra field or two.

### Anti-Pattern 3: Mocking methods the test depends on

WRONG:
```python
# Mock prevents the config write that duplicate detection depends on
mock.patch("write_config", return_value=None)

def test_detects_duplicate():
    add_server(config)  # Config not written because mocked
    add_server(config)  # No duplicate detected because first write was mocked
```

RIGHT: Before mocking a method, trace the dependency chain. If your test's assertions depend on that method's side effects, do not mock it. Mock at a lower level (the actual slow/external operation) instead.

**Gate:** Before mocking any method:
1. What side effects does the real method have (state changes, writes, enqueued jobs, emitted events)?
2. Does this test depend on any of those side effects?
3. If yes, mock at a lower level or don't mock at all.

### Mocking red flags (stop and reconsider)

- Mock setup is longer than the test logic.
- The test fails when you remove a mock, and you cannot explain why.
- You are asserting only on `mock.called` / test IDs without testing outcomes.
- You find yourself thinking "I'll mock this to be safe" because you don't understand the dependency.
- You cannot clearly explain what the mock is replacing and why it's safe to replace it.

If one or more of these are true, re-evaluate your mocking strategy before adding more mocks.

---

## Cases Checklist

Execute these steps after the strategy rule has run:

### Step 1: Determine mocking strategy
Execute Decision Tree 3 for each dependency. State mocking decisions.

### Step 2: Check wrapper coverage
If code wraps external API:
- List all public methods with payload construction or branching.
- Verify each has tests for payload shape and error handling.
- Add missing tests.

### Step 3: Check exception coverage
If the codebase has exception classes that are part of the public API or used by other code, ensure each has at least one smoke test.

### Step 4: Apply edge case checklist (per input or branch)

For **each** input or branch that affects behavior (event payload keys, query params, response fields, config):

- [ ] Identify which inputs are **collections** (e.g. `Records`, `to_number`, `Entries`). Test empty `[]`, one item, and (where relevant) many.
- [ ] Identify which inputs are **nullable** or type-sensitive (e.g. `body`, `text`, `to_number`). Test `None`, `""`, populated, and (if from JSON) literal `"null"`; test wrong type (e.g. string where list is expected) if the code doesn't validate.
- [ ] **Missing keys:** For dict/JSON inputs, test payloads that omit required keys (e.g. `date_field`, `media_url`, `s3_prefix`, `dynamodb.Keys`) and assert the code returns a clear error or documented behavior.
- [ ] Error/exception paths and state transitions (if applicable): both transition and no-op cases.
- [ ] Type-based branches: all types covered with correct payloads.

### Step 5: Verify HTTP/API error handling

For methods that make HTTP calls or call external APIs:

- [ ] Success response (200/201)
- [ ] Client errors (4xx) raise or handle appropriately; assert the exact exception or return the code produces.
- [ ] Server errors (5xx): assert the **exact** exception type and message substring the handler raises (e.g. wrapped `Exception('Error processing record...')`). Prefer `match=` that matches the full wrapper message where it matters.
- [ ] Empty/null responses handled correctly

### Step 6: Summarize planned cases (required before implementation)

**Do not implement tests until this step is done.** List every test case you will implement:

- Test name (e.g. `test_LambdaHandler_EmptyRecords_DoesNotRaise`)
- One-line scenario (e.g. "Event with Records=[]; handler must not crash and must not call downstream.")
- Which checklist item it satisfies (e.g. "Collections: empty").

Pass this list to the style rule (or next step) for implementation. If generating tests in one go, produce this list first, then implement.

---

## Before considering tests complete

Run this final pass before treating the test suite as done:

- [ ] Every branch in the code under test has at least one test (including re-raise paths like `except ClientError: raise e`).
- [ ] Every test that uses `pytest.raises(...)` asserts the type and message pattern that the code actually raises.
- [ ] For event/payload inputs: empty collection, missing key, and wrong-type cases are covered where the code can fail or behave differently.
- [ ] Infra/template assertions match the current stack (counts, resource types); no unexplained magic numbers.
