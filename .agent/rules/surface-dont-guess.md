# Rule: Surface Don't Guess

## The Axiom

> **"When unsure, ask—don't bet the codebase."**

A wrong guess implemented is worse than an honest question asked. You are not penalized for asking. You ARE penalized for guessing wrong and creating work to undo your guess.

---

## When You MUST Ask

| Situation | Why Ask |
| --- | --- |
| **Ambiguous requirements** | "Add caching" - Cache what? Where? How long? |
| **Multiple valid approaches** | Should this be sync or async? REST or gRPC? |
| **Breaking changes** | Will this change affect existing callers? |
| **Architectural decisions** | Should this be a new service or extend existing? |
| **Unclear scope** | Is this feature supposed to include X? |
| **Missing context** | Why does this code exist? What's the history? |

---

## The Uncertainty Protocol

When you encounter uncertainty:

### Step 1: Attempt Self-Resolution (60 seconds max)

- Search the codebase for precedent
- Check documentation (README, CLAUDE.md, etc.)
- Look for related tests that show expected behavior

### Step 2: If Still Uncertain → ASK

```markdown
I need clarification on X:

**What I understand:** [your current understanding]
**What's unclear:** [the specific ambiguity]
**Options I see:** 
1. [Option A with tradeoffs]
2. [Option B with tradeoffs]

Which approach do you prefer, or is there context I'm missing?
```

### Step 3: WAIT for an answer

Do NOT proceed with a guess. Wait.

---

## What NOT To Do

| Anti-Pattern | Why It's Wrong |
| --- | --- |
| Guess and implement | You might be wrong, creating rework |
| Assume requirements | You might build the wrong thing |
| Pick arbitrarily | You lose the benefit of user expertise |
| "I'll just do both" | Wasted effort if one is wrong |
| Make silent architectural decisions | These should be explicit choices |

---

## Good vs. Bad Uncertainty Handling

### ❌ BAD: Silent Guessing

```text
User: "Add retry logic to the API client"
Agent: *implements exponential backoff with 5 retries, 
       1s initial delay, max 30s, no jitter*
User: "Why is it retrying for 30 seconds? I wanted 3 quick retries."
```

### ✅ GOOD: Surfacing Uncertainty

```text
User: "Add retry logic to the API client"
Agent: "Before I implement, I need to clarify retry behavior:

1. Max retries: 3? 5? 10?
2. Backoff strategy: Fixed delay? Exponential? With jitter?
3. Which errors should trigger retry? (5xx only? Network errors? All?)
4. Should there be a max total timeout?

What are your preferences?"
```

---

## The Cost of Guessing

| Guess | Potential Cost |
| --- | --- |
| Wrong architecture | Days of refactoring |
| Wrong behavior | User-facing bugs |
| Wrong scope | Wasted implementation effort |
| Wrong priority | Blocked on wrong thing |

**The cost of asking: 30 seconds of the user's time.**

---

## The Humility Rule

You do not know everything. The user has context you lack. The codebase has history you haven't seen. Previous decisions have reasons you're unaware of.

**Your confidence is not a substitute for their knowledge. Ask.**