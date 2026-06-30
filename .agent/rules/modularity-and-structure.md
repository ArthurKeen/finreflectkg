# Rule: Modularity and Structure

## The Axiom

> **"Everything has a place. Put everything in its place."**

A well-organized codebase is a navigable codebase. Files have size limits. Directories have purposes. Documents have homes. When you ignore structure, you create chaos for every future developer.

---

## File Size Limits

| File Type | Max Lines | Action If Exceeded |
| --- | --- | --- |
| **Source code** (`.go`, `.ts`, `.tsx`) | 1500 | Split into multiple files |
| **Test files** (`_test.go`, `.test.ts`) | 2000 | Split by test category |
| **Config files** | 500 | Use includes/imports |
| **Documentation** | 1000 | Split into sections |

### How to Split Large Files

```text
# Before: One massive file
handlers.go (2500 lines)

# After: Split by domain
handlers/
├── user_handlers.go (400 lines)
├── auth_handlers.go (350 lines)
├── admin_handlers.go (300 lines)
├── api_handlers.go (450 lines)
└── internal.go (200 lines)
```

### Signs a File Needs Splitting

- You can't find things without `Ctrl+F`
- The file has multiple unrelated concerns
- You're constantly scrolling
- File outline is overwhelming
- Multiple people need to edit it simultaneously

---

## Directory Structure Awareness

Before creating files, understand where they belong:

### NERDide Project Structure

```text
nerdide/
├── cmd/                    # Entry points (main.go files)
├── internal/               # Private packages
│   ├── agents/             # Kitchen Brigade agents
│   │   └── permanent/      # Always-running agents
│   ├── api/                # REST/gRPC handlers
│   ├── storage/            # Database implementations
│   ├── vector/             # Vector operations
│   └── ...
├── pkg/                    # Public packages (clients, SDKs)
├── web/                    # Frontend code
├── docs/                   # Documentation
├── configs/                # Configuration files
├── deployments/            # K8s, Docker configs
├── tests/                  # E2E and integration tests
└── .agent/                 # AI agent configuration
    ├── rules/              # Agent behavior rules
    ├── skills/             # Agent capabilities
    └── workflows/          # Automated workflows
```

### File Placement Rules

| File Type | Goes In | NOT In |
| --- | --- | --- |
| New handler | `internal/api/rest/` or `internal/api/grpc/` | Root directory |
| New agent | `internal/agents/permanent/<name>/` | `internal/agents/` directly |
| Shared types | `internal/core/` or appropriate `types.go` | Random location |
| Tests | Next to source file as `*_test.go` | Separate `tests/` folder (except E2E) |
| Configs | `configs/` | Root directory |
| Scripts | `scripts/` | Root directory |

---

## Generated Document Placement

When you generate documents (analysis, audits, plans), they go in specific places:

### Project Documentation (Permanent)

```text
docs/
├── architecture/           # Design decisions, ADRs
│   └── decisions/          # Architecture Decision Records
├── api/                    # API documentation
├── guides/                 # How-to guides
├── analysis/               # Code analysis reports
│   ├── audits/             # Security/performance audits
│   └── reports/            # Generated analysis reports
└── research/               # Research findings
```

### When to Use Which Location

| Document Type | Location | Why |
| --- | --- | --- |
| Task planning for current work | `~/.gemini/.../task.md` | Ephemeral, conversation-scoped |
| Implementation proposal | `~/.gemini/.../implementation_plan.md` | Needs user approval |
| Audit of codebase security | `docs/analysis/audits/` | Permanent reference |
| Architecture decision | `docs/architecture/decisions/` | Long-term record |
| API changes | `docs/api/` | User-facing documentation |
| Research findings | `docs/research/` or `memory-bank/` | Knowledge preservation |

---

## Module Cohesion Rules

### Each Package Should

| Requirement | Explanation |
| --- | --- |
| Have a single responsibility | One reason to change |
| Expose a minimal public API | Only what callers need |
| Hide implementation details | Internal helpers unexported |
| Be independently testable | Not dependent on everything |

### File Organization Within Package

```text
mypackage/
├── mypackage.go            # Main types and public API
├── helpers.go              # Internal utilities
├── types.go                # Type definitions (if many)
├── errors.go               # Error types (if many)
├── mypackage_test.go       # Tests for main file
└── helpers_test.go         # Tests for helpers
```

---

## The Structure Audit Checklist

Before creating any file, verify:

| Check | Question |
| --- | --- |
| **Location** | Is this the right directory for this file? |
| **Naming** | Does the name follow existing conventions? |
| **Size** | Will this file stay under limits? |
| **Cohesion** | Does this file belong with its neighbors? |
| **Discoverability** | Can someone find this file intuitively? |

---

## Anti-Patterns

| What You Did | What You Should Have Done |
| --- | --- |
| Created `stuff.go` in root | Put in appropriate `internal/` subdirectory |
| Made 3000-line handler file | Split into domain-specific handler files |
| Put audit in conversation artifacts | Put in `docs/analysis/audits/` |
| Created `my_test.go` in `tests/` | Put next to source as `my_test.go` |
| Added `utils.go` to random package | Used existing utils or created shared package |

---

## The Navigation Rule

> A new developer should be able to find any file based solely on what it does, without searching.

If they want user handlers, they look in `internal/api/handlers/user.go`.  
If they want auth logic, they look in `internal/auth/`.  
If they want agent rules, they look in `.agent/rules/`.

**Structure is not bureaucracy—it's navigation.**