# Rule: Incremental Over Atomic

## The Axiom

> **"Small steps that individually work > Large steps that eventually work."**

Big-bang changes are high-risk gambles. They break multiple things simultaneously, make debugging impossible, and force all-or-nothing rollbacks. Incremental changes are safe, reviewable, and reversible.

---

## The Incremental Protocol

### Instead of Big Bang → Do Incremental Slices

| Big Bang Approach | Incremental Approach |
| --- | --- |
| Refactor entire module at once | Refactor one function, verify, commit, repeat |
| Add feature + tests + docs in one PR | Add types first → then logic → then tests → then docs |
| Replace old system with new | Run both in parallel, migrate gradually, then remove old |
| Fix all linter errors at once | Fix one category, verify, commit, repeat |

---

## Slice Size Guidelines

Each increment should be:

| Property | Guideline |
| --- | --- |
| **Verifiable** | Can be tested independently |
| **Reversible** | Can be rolled back without affecting other changes |
| **Reviewable** | Small enough to understand in < 5 minutes |
| **Deployable** | Doesn't break the build in isolation |

**Rule of thumb:** If an increment takes more than 30 minutes, it's too big. Slice smaller.

---

## The Working State Rule

At every checkpoint, the codebase MUST:

1. **Compile** - No build errors
2. **Pass tests** - No regressions
3. **Be functional** - No broken features

If your change creates a broken intermediate state, you're doing too much at once.

---

## Refactoring Pattern

### ❌ BAD: All-At-Once

```text
1. Start refactoring module
2. Change 15 files
3. Break 8 tests
4. Spend 2 hours fixing ripple effects
5. Finally get it working
6. One big commit
```

### ✅ GOOD: Incremental

```text
1. Add new function alongside old
2. Verify new function works (commit)
3. Migrate one caller to new function
4. Verify still works (commit)
5. Migrate next caller (commit)
6. Repeat until all callers migrated
7. Remove old function (commit)
```

---

## Feature Addition Pattern

### ❌ BAD: Kitchen Sink PR

```text
feat: Add user authentication

- Added login endpoint
- Added logout endpoint  
- Added session management
- Added password reset
- Added email verification
- Added OAuth integration
- Added 2FA
- Added user preferences
- Added 47 new files
```

### ✅ GOOD: Layered PRs

```text
PR 1: feat(auth): Add session storage types and interfaces
PR 2: feat(auth): Add login endpoint with session creation
PR 3: feat(auth): Add logout endpoint with session cleanup
PR 4: feat(auth): Add password reset flow
PR 5: feat(auth): Add email verification
...
```

---

## The Safety Net

Incremental changes provide:

| Benefit | How |
| --- | --- |
| **Easy debugging** | Only last small change could have broken it |
| **Easy rollback** | Revert one commit, not twenty |
| **Easy review** | Reviewer understands small changes |
| **Continuous progress** | Always have something working |
| **Parallel work** | Others can work on merged increments |

---

## The Atomic Anti-Pattern Detector

If you find yourself:

- Changing more than 5 files at once → **Slice smaller**
- Working for 1+ hour without a commit → **Checkpoint now**
- Unable to describe the change in one sentence → **It's too big**
- Afraid to run tests because "it's not done yet" → **You've gone too far**

---

## The Mantra

> Every commit should leave the codebase better than before, and never worse.

**Small steps. Verify each one. Never break the build.**