# Rule: Wiring Over Deletion (The Prime Directive of Integration)

## 1. The Core Axiom

> **"Unused code often represents missing features, not garbage."**

When you see a squiggly line under an import, variable, parameter, or method, it is NOT a request to delete it. It is a request to **finish the implementation**.

Agents often fall into the "Linter Trap": prioritizing a clean console over a complete feature set. This leads to regression where partially implemented features are stripped out instead of being connected.

**The Rule:** You are FORBIDDEN from deleting "unused" code without first proving it is truly obsolete.

## 2. Technical Decision Matrix

Before deleting ANY entity run this protocol matching your specific language:

### 🐍 Golang Wiring Protocol

* **⚠️ Warning**: `VAR declared but not used`
  * **Diagnosis**: You calculated a value (e.g., `score`) but didn't use it.
  * **Resolution**:
    * **Log It**: `logrus.WithField("score", score).Info("Processing complete")`
    * **Return It**: Add it to the return parameters if it's valuable API data.
    * **Trace It**: `span.SetAttributes(attribute.Int("score", score))`
  * **❌ FORBIDDEN**: `_ = score` (The "Ostrich Algorithm" - burying your head in the sand).

* **⚠️ Warning**: `CTX parameter unused`
  * **Diagnosis**: You broke the cancellation propagation chain.
  * **Resolution**: Pass `ctx` to *every* DB call, HTTP request, or sub-function.
  * **Example**: Change `db.Get(...)` to `db.Get(ctx, ...)`

* **⚠️ Warning**: `ERR variable unused`
  * **Diagnosis**: You are swallowing an error. This is a critical bug.
  * **Resolution**: `if err != nil { return fmt.Errorf("context: %w", err) }`

### ⚛️ React/TypeScript Wiring Protocol

* **⚠️ Warning**: `'MyIcon' is defined but never used`
  * **Diagnosis**: You imported an asset but forgot to render it.
  * **Resolution**:
    * **Visual Context**: "Where does this icon belong?" -> Add it to the button or header.
    * **Fallback**: Use it as a placeholder or empty state.
    * **Example**: `<Button icon={<MyIcon />} ... />`

* **⚠️ Warning**: `Prop 'isEnabled' is defined but never used`
  * **Diagnosis**: The parent component is trying to control this component, but you ignored it.
  * **Resolution**: Check the JSX.
    * **Conditional Rendering**: `{isEnabled && <Content />}`
    * **Class/Style Toggling**: `className={isEnabled ? 'active' : 'inactive'}`
    * **Logic Gate**: `if (!isEnabled) return null;`

* **⚠️ Warning**: `useEffect has missing dependencies`
  * **Diagnosis**: Your effect relies on stale data.
  * **Resolution**: **DO NOT** remove the dependency or use `eslint-disable`.
    * **Correct**: Stabilize the dependency (use `useCallback`, `useMemo`, or move definition inside effect).

### 🔍 Mangle/Datalog Wiring Protocol

* **⚠️ Warning**: `Predicate 'foo' is defined but never used`
  * **Diagnosis**: You defined a rule or fact that contributes to nothing.
  * **Resolution**:
    * **Chain It**: Does another rule need this? `bar(X) :- foo(X, Y)`.

### 📦 Unwired Imports Protocol

* **⚠️ Warning**: `'some-lib' is imported but never used`
  * **Diagnosis**: You planned to use a library feature (e.g., specific date formatter, UI component) but forgot to implement it.
  * **Resolution**:
    * **Implement It**: Use the imported function/component in the code.
    * **Check Docs**: Did you mean to use a side-effect import (`import 'lib/styles.css'`)?
  * **❌ FORBIDDEN**: Deleting the import just to silence the linter, unless the entire feature using it was scrapped.

### 🧪 Testing Wiring Protocol

* **⚠️ Warning**: `Unused write to field 'Reason'` (in test helpers/listeners)
  * **Diagnosis**: You represent a "tamper attempt" or "setup step" but never verify if it succeeded locally.
  * **Resolution**:
    * **Assert It**: `if state.Reason != "tampered" { panic("setup failed") }`
    * **Log It**: `t.Logf("Tampering with reason: %s", state.Reason)`
  * **Why**: Prove that your test setup actually executed before asserting the result.

* **⚠️ Warning**: `Unused parameter 't'` (in sub-tests)
  * **Diagnosis**: You are using the parent test context instead of the sub-test context.
  * **Resolution**: SHADOW IT. `t.Run("sub", func(t *testing.T) { ... })`
  * **Why**: Using parent `t` breaks parallel testing and error attribution.

## 3. General "Wire It" Checklist

If you find an orphan entity, ask:

1. **Semantic Value**: Does the name (`createdAt`, `status`, `ownerId`) suggest meaningful data? -> **Wire it to UI/Logs.**
2. **Structural Integrity**: Is it a parameter (`ctx`, `config`) required for system stability? -> **Pass it down.**
3. **Intent**: Was it just added in the previous turn? -> **IT IS MANDATORY TO USE IT.**

## 4. The "Linter Trap" Manifesto

> "A passing linter check on a broken feature is a failure. A failing linter check on a working feature is just a todo."

**Do not be an agent who cleans the house by throwing out the furniture.** Wire the system together.