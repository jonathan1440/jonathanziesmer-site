# Unit Testing Style

Controls HOW tests are written: naming, structure, docstrings, assertions, and test data. This rule assumes the strategy rule and cases rule have already run.

## CRITICAL RULES (never violate)

1. **NEVER use real customer data.** Use synthetic data only.
2. **NEVER write tests with logic.** No conditionals, loops, or computation in test code. Split into separate tests or use parameterization.
3. **ALWAYS use the exact 5-header docstring format specified below.** Every generated test MUST include all five headers: Behavior, Scenario/inputs, Expected outcome, Why this case, Justification. No exceptions. No abbreviated format.
4. **ALWAYS use Arrange-Act-Assert structure.** Mark each section with comments (`# Arrange`, `# Act`, `# Assert`) for clarity.

---

## Docstring Format (MANDATORY for all generated tests)

Every test created or modified by an AI assistant MUST include a docstring using this EXACT structure. All five headers are required. Do not omit any header. Do not rename headers. Do not merge headers.

```
- **Behavior:** Describe what business/API behavior is being exercised in plain language (not just the function name).
- **Scenario/inputs:** Call out the specific scenario or inputs that make this test different from its siblings.
- **Expected outcome:** State what must happen or must *not* happen in domain terms, not just the assertion syntax.
- **Why this case:** Explain why this case exists or is non-obvious.
- **Justification:** One sentence tying this test to the rules. No full chain-of-thought.
```

---

## Naming Format

`test_MethodUnderTest_Scenario_ExpectedBehavior` (PascalCase for method and scenario). A failing test name alone must tell you what broke without reading test code.

Examples:
- `test_ProcessPayment_InsufficientFunds_RaisesPaymentError`
- `test_GetValue_NoneInput_ReturnsDefault`
- `test_BuildParams_EmailIsNone_OmitsEmailKey`

---

## Arrange-Act-Assert Structure

Keep sections visually distinct. One Act per test.

```python
def test_CalculateTotal_WithDiscount_AppliesPercentage():
    """
    - **Behavior:** Calculating cart total with a percentage discount applied.
    - **Scenario/inputs:** Single item at $100, 10% discount.
    - **Expected outcome:** Total is $90 after discount.
    - **Why this case:** Baseline happy path for discount application.
    - **Justification:** Business logic outcome requires at least one test per distinct calculation path.
    """
    # Arrange
    cart = Cart(items=[Item(price=100)])
    discount = Discount(percent=10)

    # Act
    total = calculate_total(cart, discount)

    # Assert
    assert total == 90
```

---

## One Behavior Per Test

ALLOWED: Multiple asserts verifying facets of ONE outcome.
```python
def test_ParseUser_ValidInput_ReturnsUserObject():
    """
    - **Behavior:** Parsing a valid JSON payload into a User object.
    - **Scenario/inputs:** Well-formed JSON with name and email fields populated.
    - **Expected outcome:** Returned User object has correct name and email attributes.
    - **Why this case:** Happy path for the primary parsing function.
    - **Justification:** Business logic outcome; every parser needs at least one valid-input test.
    """
    user = parse_user(valid_json)
    assert user.name == "Alice"
    assert user.email == "alice@example.com"  # Same outcome: parsing worked
```

NOT ALLOWED: Multiple unrelated behaviors in one test.
```python
# BAD: Tests parsing AND logging in one test
def test_ParseUser_ValidInput_Works():
    user = parse_user(valid_json)
    assert user.name == "Alice"
    assert logger.info.called  # Unrelated behavior
```

---

## Parameterized Tests

Use when same logic applies to multiple inputs:

```python
@pytest.mark.parametrize("input_type,expected", [
    ("employee", "standard"),
    ("contractor", "limited"),
    ("executive", "premium"),
])
def test_GetAccessLevel_ReturnsCorrectLevel(input_type, expected):
    """
    - **Behavior:** Mapping user type to access level.
    - **Scenario/inputs:** Parameterized across employee, contractor, executive types.
    - **Expected outcome:** Each type maps to its designated access level.
    - **Why this case:** Covers all three branches of the type-to-level mapping.
    - **Justification:** Branching logic; each meaningful branch must be exercised.
    """
    assert get_access_level(input_type) == expected
```

Sweet spot: 3-8 cases. Beyond 8, consider separate named tests for clarity.

**When to use parameterization:**
- Testing the same behavior with different input values
- Covering multiple branches of type-based logic (e.g., employee/contractor/student)
- Boundary value testing (min/max/zero)

**When NOT to use parameterization:**
- Different behaviors or assertions per case
- Complex setup that varies significantly per case
- When test names would be unclear

---

## Complete Example

The following tests illustrate all style rules applied together: naming, AAA, five-part docstrings, nullable handling, parameterization, state transitions, and error path assertions.

```python
def test_BuildUserParams_EmailIsNone_OmitsEmailKey():
    """
    - **Behavior:** Building API request parameters for user update.
    - **Scenario/inputs:** Email field is None (not empty string, not missing from input dict).
    - **Expected outcome:** The resulting params dict must not contain an "email" key at all, rather than containing email=None.
    - **Why this case:** The upstream API interprets email=None as "clear the email," which differs from omitting the key (meaning "don't change it"). Previous bug in JIRA-1234 caused unintended email clears.
    - **Justification:** High-risk edge case per decision tree; nullable value handling requires separate tests for None vs empty vs populated.
    """
    # Arrange
    mock_client = Mock(spec=ExternalClient)
    wrapper = WrapperClass(client=mock_client)
    user_data = {"name": "Alice", "email": None}

    # Act
    params = wrapper.build_user_params(user_data)

    # Assert
    assert "email" not in params, "email=None should omit key, not send null"
    assert params["name"] == "Alice"


@pytest.mark.parametrize("account_type,expected_payload", [
    ("employee", {"wd_user_type": "employee", "access_level": "standard"}),
    ("student_worker", {"wd_user_type": "student_worker", "access_level": "limited"}),
    ("non_employee_student", {"wd_user_type": "student_applicant", "access_level": "limited"}),
])
def test_AddCustomAttributes_ByAccountType_CorrectPayload(account_type, expected_payload):
    """
    - **Behavior:** Adding custom attributes based on account type.
    - **Scenario/inputs:** Parameterized across employee, student_worker, non-employee student types.
    - **Expected outcome:** Each type generates correct payload with appropriate wd_user_type and access_level.
    - **Why this case:** Covers all branches of type-to-payload mapping.
    - **Justification:** Branching logic per cases rule; each meaningful branch must be exercised with correct payload assertion.
    """
    # Arrange
    mock_client = Mock(spec=ExternalClient)
    wrapper = WrapperClass(client=mock_client)

    # Act
    wrapper.add_custom_attributes(user_id=123, account_type=account_type)

    # Assert
    mock_client.update_custom_attributes.assert_called_once()
    call_args = mock_client.update_custom_attributes.call_args
    assert call_args[1]["custom_attributes"] == expected_payload


def test_ReactivateUser_InactiveUser_UpdatesStatusAndReturnsUser():
    """
    - **Behavior:** Reactivating an inactive user account.
    - **Scenario/inputs:** User exists and is currently inactive (status=0).
    - **Expected outcome:** Calls update_user with status=1, state=0, and returns updated user.
    - **Why this case:** State transition case; inactive → active.
    - **Justification:** State transitions per cases rule; test both transition and no-op cases.
    """
    # Arrange
    mock_client = Mock(spec=ExternalClient)
    wrapper = WrapperClass(client=mock_client)
    inactive_user = {"id": 123, "status": 0, "state": 2}
    mock_client.get_user.return_value = inactive_user
    mock_client.update_user.return_value = {"id": 123, "status": 1, "state": 0}

    # Act
    result = wrapper.reactivate_user(user_id=123)

    # Assert
    mock_client.update_user.assert_called_once_with(
        123,
        status=1,
        state=0,
        member_of=[]
    )
    assert result["status"] == 1


def test_ReactivateUser_AlreadyActive_NoUpdateReturnsUser():
    """
    - **Behavior:** Reactivating a user who is already active.
    - **Scenario/inputs:** User exists and is already active (status=1).
    - **Expected outcome:** No update call made, returns user as-is.
    - **Why this case:** No-op case for idempotent operation.
    - **Justification:** State transitions per cases rule; test both transition and no-op cases.
    """
    # Arrange
    mock_client = Mock(spec=ExternalClient)
    wrapper = WrapperClass(client=mock_client)
    active_user = {"id": 123, "status": 1, "state": 0}
    mock_client.get_user.return_value = active_user

    # Act
    result = wrapper.reactivate_user(user_id=123)

    # Assert
    mock_client.update_user.assert_not_called()
    assert result == active_user


def test_SendInvite_ServerError_RaisesUserProvisioningException():
    """
    - **Behavior:** Sending account invitation via HTTP API.
    - **Scenario/inputs:** API returns 500 server error.
    - **Expected outcome:** Raises UserProvisioningException with error details.
    - **Why this case:** Error path; server errors must be handled gracefully.
    - **Justification:** Error handling per cases rule; test 4xx, 5xx, and exception paths.
    """
    # Arrange
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    with patch('requests.post', return_value=mock_response):
        invite = AccountInvite(api_key="test_key")

        # Act & Assert
        with pytest.raises(UserProvisioningException, match="500.*Internal Server Error"):
            invite.send_invite(email="test@example.com")
```

---

## Test Data Rules

- Use MINIMAL data that demonstrates behavior.
- Use NAMED CONSTANTS or builders, not magic literals.
- Use FACTORIES for complex object construction.
- NEVER use real customer data.

### Shared Helpers vs Inline Setup

Two valid approaches for test setup:

**Shared helpers** (good for reducing duplication):
```python
def _wrapper_with_mock_client():
    """Helper to create wrapper with mocked client."""
    mock_client = Mock()
    return WrapperClass(client=mock_client), mock_client

def _make_user(username="testuser", email="test@example.com"):
    """Helper to create test user with defaults."""
    return {"username": username, "email": email}
```

**Inline setup** (good for clarity and explicitness):
```python
def test_UpdateUser_ValidInput_CallsClient():
    """..."""
    # Arrange
    mock_client = Mock()
    wrapper = WrapperClass(client=mock_client)
    user_data = {"username": "testuser", "email": "test@example.com"}

    # Act
    wrapper.update_user(user_data)

    # Assert
    mock_client.update.assert_called_once()
```

Choose based on:
- Use helpers when setup is repeated across many tests
- Use inline when setup is test-specific or when clarity is more important than brevity
- Keep helper setup shorter than test logic

---

## Assertions

- Assert against KNOWN expected values, not recomputed values.
- Use SPECIFIC assertions: `assertEqual`, `assertRaises`, `assertIn`.
- Add MESSAGES for non-obvious assertions: `assert x == y, "x should equal y because..."`
- **Assert on behavior, not just mock calls**: Verify return values, payloads, and side effects, not just that a mock was called.

### Assertion Patterns

**Good assertions** (test real behavior):
```python
# Assert on return value
assert result == expected_user

# Assert on payload shape and values
mock_client.update.assert_called_once_with(
    user_id=123,
    payload={"status": 1, "role": "admin"}
)

# Assert on key presence/absence
assert "email" not in params  # email=None should omit key
assert params["name"] == "Alice"

# Assert on exception type and message
with pytest.raises(UserProvisioningException, match="Invalid user"):
    process_user(invalid_data)
```

**Bad assertions** (test mock existence, not behavior):
```python
# Bad: only checks mock was called, not what it was called with
assert mock_client.update.called

# Bad: doesn't verify the actual behavior
assert mock_sidebar.called
```

### Infra and snapshot assertions

When asserting on synthesized templates or resource counts (e.g. CDK, Terraform):

- Derive the expected value from the code under test (e.g. count of Lambda constructs in the stack) or from a documented contract.
- If a literal (e.g. `4`) is used, add a brief comment or docstring explaining the source (e.g. "Stack defines validation_lambda, mmsstore_lambda, ...; total 4").
- Updating the stack or template should prompt a review of these assertions so they stay in sync.

---

## Style Checklist

Execute these steps when writing or modifying tests:

### Step 1: Write tests
- Follow naming format: `test_MethodUnderTest_Scenario_ExpectedBehavior`
- Use Arrange-Act-Assert structure with comments marking each section.
- One behavior per test.
- Use parameterization for 3-8 variants of the same logic.

### Step 2: Verify docstrings
Review EVERY generated test. Confirm the docstring contains ALL FIVE required headers:
1. **Behavior**
2. **Scenario/inputs**
3. **Expected outcome**
4. **Why this case**
5. **Justification**

If any header is missing, add it before presenting the test. This is not optional.

### Step 3: Verify test data
- No real customer data.
- No magic literals without named constants.
- Minimal data that demonstrates the behavior.

### Step 4: Explain your decisions
In your response, briefly state:
- Why you're testing this code
- What scenarios you're covering
- What you're intentionally skipping and why

---

## Test Organization

### Splitting Test Files

For large modules with many methods, consider splitting tests into multiple files:

**Core vs Additional pattern:**
```
tests/
  test_wrapper.py          # Core wrapper methods
  test_wrapper_additional.py  # Additional/secondary methods
```

This allows running core tests separately from additional tests, useful for:
- Faster feedback loops during development
- Separating high-priority from low-priority tests
- Organizing tests by feature area

**When to split:**
- Module has >15 public methods
- Clear separation between core and secondary functionality
- Different test priorities (high-priority core vs medium-priority additional)

**When NOT to split:**
- Small modules (<10 methods)
- No clear separation of concerns
- Would create confusion about where to find tests

### Suite Documentation

For comprehensive test suites, consider adding a `tests/README.md` that documents:

1. **Coverage summary**: What modules/areas are tested
2. **Test counts**: Number of tests per module or area
3. **How to run**: Commands for running all tests, specific suites, or individual files
4. **Strategy**: Testing priorities, patterns used, what's intentionally not tested
5. **Patterns**: Common patterns like nullable handling, wrapper method testing, error path coverage
6. **Docstring format**: Reference to the 5-part docstring structure

This is especially valuable for:
- Large codebases with multiple test files
- Teams with multiple contributors
- Projects where testing strategy needs to be explicit
