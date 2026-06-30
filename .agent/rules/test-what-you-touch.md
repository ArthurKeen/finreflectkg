# Rule: Test What You Touch

## The Axiom

> **"Every code change deserves a test change."**

If you changed code, you changed behavior. If you changed behavior, tests must verify that behavior. Untested code is unverified code—and unverified code is broken code waiting to happen.

---

## The Testing Mandate

| Code Change Type | Required Test Change |
| --- | --- |
| New function | New unit test |
| New endpoint | New integration test |
| Bug fix | Regression test (test that would have caught the bug) |
| Refactor | Run existing tests, add any missing coverage |
| New error path | Test that exercises the error path |
| Config change | Test with different config values |

---

## Test Coverage Requirements

### For New Functions

```go
// ✅ Test the happy path
func TestMyFunction_Success(t *testing.T) { ... }

// ✅ Test error paths
func TestMyFunction_InvalidInput(t *testing.T) { ... }
func TestMyFunction_EmptyInput(t *testing.T) { ... }

// ✅ Test edge cases
func TestMyFunction_BoundaryValues(t *testing.T) { ... }
```

### For Bug Fixes

```go
// ✅ The regression test - this test would have caught the bug
func TestMyFunction_Issue123_PreviouslyBrokenCase(t *testing.T) {
    // This specific input used to fail
    result := MyFunction(brokenInput)
    // Now it works
    assert.Equal(t, expectedOutput, result)
}
```

### For Refactors

- All existing tests MUST still pass
- If existing tests don't cover the refactored path, add tests FIRST

---

## The "Touched Files" Rule

For every file you modify, ask:

| Question | If No → |
| --- | --- |
| Is there a corresponding `_test.go` file? | Create one |
| Does the test file cover the code I changed? | Add coverage |
| Did I run the tests after my change? | Run them now |

---

## Test Quality Standards

| Requirement | Why |
| --- | --- |
| Tests must be deterministic | No flaky tests |
| Tests must be fast | Slow tests don't get run |
| Tests must be isolated | No shared state between tests |
| Tests must have clear names | `TestX_WhenY_ShouldZ` format |
| Tests must assert behavior | Not just "no panic" |

---

## Anti-Patterns

| What You Did | What You Should Have Done |
| --- | --- |
| "The code works, I tested manually" | Write an automated test |
| "Tests take too long to write" | Tests are part of the feature |
| "I'll add tests later" | Tests are written NOW |
| "The existing tests still pass" | Did you add tests for NEW code? |
| "It's just a small change" | Small changes still need tests |

---

## The Untested Code Tax

Every line of untested code is a future debugging session. Every bug in untested code takes 10x longer to find. Every regression in untested code is YOUR fault.

**If you wrote it, test it.**