# Rule: Read Before Write

## The Axiom

> **"Match the codebase, don't fight it."**

Before writing ANY code, you must understand what already exists. The codebase has patterns, conventions, utilities, and abstractions. Your job is to USE them, not reinvent them.

---

## The Reading Protocol

Before implementing anything, execute this search sequence:

### 1. Pattern Search

```bash
# How does the codebase already do this?
grep -r "similar_function" .
grep -r "SimilarType" .
```

### 2. Utility Search

```bash
# Is there a helper for this?
grep -r "util" --include="*.go" .
grep -r "helper" --include="*.go" .
grep -r "common" --include="*.go" .
```

### 3. Existing Implementation Search

```bash
# Has someone already solved this?
grep -r "the_thing_im_trying_to_do" .
```

### 4. Test Pattern Search

```bash
# How are similar things tested?
grep -r "TestSimilar" --include="*_test.go" .
```

---

## What You Must Find Before Writing

| Before Writing | Find First |
| --- | --- |
| New struct/type | Existing similar types |
| New function | Existing utilities with same behavior |
| New endpoint | Existing endpoint patterns |
| New test | Existing test helpers/patterns |
| New error type | Existing error conventions |
| New config field | Existing config structure |

---

## Pattern Matching Requirements

When you find existing patterns, you MUST:

1. **Use the same naming conventions** - If the codebase uses `FooHandler`, don't create `handleFoo`
2. **Use the same file organization** - If handlers go in `handlers/`, don't put yours in `api/`
3. **Use the same error handling** - If the codebase wraps errors, wrap yours
4. **Use the same logging** - If the codebase uses structured logging, use it
5. **Use existing utilities** - Don't write `formatTime()` if `utils.FormatTime()` exists

---

## The Duplication Detector

Before creating anything new, ask:

| Question | If Yes → |
| --- | --- |
| Does this function already exist? | Use it |
| Does a similar type already exist? | Extend or reuse it |
| Is there a util/helper for this? | Call it |
| Is there an established pattern for this? | Follow it |

---

## Anti-Patterns

| What You Did | What You Should Have Done |
| --- | --- |
| Created `stringUtils.go` | Searched for existing string utilities |
| Added error type `MyError` | Found existing error package/patterns |
| Wrote custom validation | Found existing validation framework |
| Made new HTTP client wrapper | Found existing client utilities |

---

## The Codebase Respect Rule

The codebase was here before you. It will be here after you. Your job is to make it *more* consistent, not less. Every new pattern you introduce is a burden on future maintainers.

**Read first. Match the patterns. Then write.**