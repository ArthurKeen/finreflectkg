# Rule: Checkpoint Regularly

## The Axiom

> **"Commit early, push often, never lose work."**

Large, uncommitted changesets are disasters waiting to happen. If your session crashes, if the user cancels, if anything goes wrong—hours of work vanish. Checkpointing is not optional; it is survival.

---

## Checkpoint Triggers

You MUST commit and push when:

| Trigger | Why |
| --- | --- |
| **Feature complete** | Logical unit of work done |
| **Tests passing** | Known-good state worth preserving |
| **Before risky refactor** | Safety net if refactor fails |
| **After ~30 minutes of work** | Time-based protection |
| **Before switching tasks** | Clean handoff point |
| **Before ending session** | Never leave work uncommitted |

---

## Git Discipline

### Commit Messages

```bash
# ✅ GOOD: Descriptive, scoped
git commit -m "feat(wormhole): wire initializeCentroids to respect config"
git commit -m "fix(aboyeur): integrate createWorkItemsFromChecklist"
git commit -m "test(seaweed): add encryption error path coverage"

# ❌ BAD: Vague, lazy
git commit -m "updates"
git commit -m "wip"
git commit -m "fix stuff"
```

### Commit Scope

- One logical change per commit
- If you can't describe it in one line, it's too big
- Related changes together, unrelated changes separate

### Push Frequency

```bash
# After every commit, push immediately
git push origin <branch>
```

**There is no reason to have unpushed commits.** Push is free. Losing work is expensive.

---

## The Recovery Rule

If you ever find yourself saying "I lost an hour of work because..."—you violated this rule. The answer is always: **commit and push more often**.

---

## Quick Reference

```bash
# The rhythm of safe development
git add -A
git commit -m "feat(scope): description"
git push origin HEAD

# Before any risky operation
git stash  # or commit first

# When in doubt
git status  # What's uncommitted?
git log -1  # What was my last checkpoint?
```

**Checkpoint. Push. Repeat.**