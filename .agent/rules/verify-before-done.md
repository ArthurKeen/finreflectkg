# Rule: Verify Before Claiming Done

## The Axiom

> **"If you didn't run it, you didn't ship it."**

Saying "I've implemented X" when you haven't verified X works is a lie. Not a mistake—a lie. Your job is to deliver *working* code, not *written* code.

---

## Mandatory Verification Steps

Before claiming ANY work is complete, you MUST:

### For Go Code

```bash
go build ./...           # Does it compile?
go test ./...            # Do tests pass?
go test -race ./...      # Any race conditions?
golangci-lint run ./...  # Any lint issues?
```

### For Frontend Code

```bash
npm run type-check   # TypeScript compiles?
npm run lint         # Lint passes?
npm run test         # Tests pass?
npm run build        # Production build works?
```

### For Any Code Change

1. **Build it** - Compilation must succeed
2. **Test it** - All tests must pass
3. **Run it** - Actually exercise the changed code path
4. **Inspect it** - Look at the output/behavior

---

## The "Done" Checklist

| Step | Question | If No → |
| --- | --- | --- |
| 1 | Did the build succeed? | Fix build errors |
| 2 | Did all tests pass? | Fix failing tests |
| 3 | Did you run the specific feature you changed? | Run it manually |
| 4 | Did you check for regressions in related areas? | Test adjacent functionality |

---

## Anti-Patterns

| What You Did | What You Should Have Done |
| --- | --- |
| "I've updated the handler" (didn't run server) | Start server, hit endpoint, verify response |
| "Fixed the test" (didn't run test suite) | Run `go test ./...` and see green |
| "Added the component" (didn't view in browser) | Run dev server, navigate to component, verify render |
| "Refactored the function" (didn't run callers) | Trace all call sites, verify they still work |

---

## The Shame Rule

If your "completed" work fails on the first verification attempt by the user, you have failed. Not partially—completely. The feature is broken, and you claimed it was done.

**Verify. Every. Time.**