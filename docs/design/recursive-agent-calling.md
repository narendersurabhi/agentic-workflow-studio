# Recursive Agent Calling

## Background

`agent.run` is a generic ReAct-style agentic loop registered as a `tool` adapter in the capability registry. It accepts an `allowed_capability_ids` list that controls which capabilities the agent may invoke at runtime. Currently, there are two gaps that prevent `agent.run` from reliably calling another `agent.run` (i.e. a sub-agent), even though the mechanical dispatch path already supports it.

This document describes those gaps, the proposed fixes, and the implementation plan.

---

## Current Architecture

### Dispatch path

```
agent_run()
  ↓ for each tool call
invoke_capability(cap_id, args)          # mcp_gateway.py
  ↓
execute_tool(adapter.tool_name, args)    # closure in tool_registry.py
  ↓
default_registry() → find "agent_run"
  ↓
_agent_run(payload, provider)            # tool_registry.py:1309
  ↓
agent_tools.agent_run(payload, provider, invoke_capability=…)
```

When `"agent.run"` appears in `allowed_capability_ids`, the dispatch path reaches `agent_tools.agent_run` recursively. Each sub-agent gets its own LLM loop, its own `max_steps` counter, and its own tool list derived from *its own* `allowed_capability_ids` (which defaults to `[]` if the parent agent did not pass it).

### Gap 1 — Empty `input_schema` exposed to the LLM

In `libs/tools/agent_tools.py`, the tool descriptor loop always produces:

```python
tools.append({
    "name": tool_name,
    "description": description,
    "input_schema": {"type": "object", "properties": {}},   # ← always empty
})
```

For capabilities whose inputs are fully specified in a JSON schema file (referenced by `input_schema_ref` in `capability_registry.yaml`), the LLM receives no field declarations. For the `agent.run` capability this is especially harmful because:

- On the **Anthropic native tool_use** path, the model uses declared `properties` to decide what arguments to supply. With an empty schema it may call the tool with an empty object `{}`, omitting `goal`, `instructions`, and `allowed_capability_ids`.
- On the **text-based ReAct** path, the model infers arguments from the description alone, which is similarly insufficient.

`agent.run` currently has `input_schema_ref: ""` in `capability_registry.yaml`, meaning no schema file is linked even though the inputs are well-defined.

### Gap 2 — No recursion depth guard

Nothing prevents a pair of agents from calling each other cyclically. Each level only stops when it exhausts its own `max_steps`. A mis-configured setup (agent A calls agent B, agent B calls agent A) produces O(max_steps²) LLM calls before terminating.

---

## Proposed Changes

### 1. Add a JSON schema file for `agent.run` inputs

Create `schemas/agent_run_capability_input.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AgentRunInput",
  "type": "object",
  "properties": {
    "goal": {
      "type": "string",
      "description": "What the agent should accomplish."
    },
    "instructions": {
      "type": "string",
      "description": "System-level instructions for the agent (optional, defaults to a generic helpful-agent prompt)."
    },
    "allowed_capability_ids": {
      "type": "array",
      "items": {"type": "string"},
      "description": "List of capability IDs the agent may invoke."
    },
    "max_steps": {
      "type": "integer",
      "minimum": 1,
      "maximum": 32,
      "description": "Maximum ReAct iterations before forcing a final answer (default 12)."
    }
  },
  "required": ["goal"]
}
```

Wire it in `capability_registry.yaml`:

```yaml
- id: agent.run
  ...
  input_schema_ref: agent_run_capability_input   # ← was ""
```

### 2. Propagate real `input_schema` when building tool descriptors

In `libs/tools/agent_tools.py`, replace the hard-coded empty schema with a lookup from the capability registry:

```python
# Before (line ~349):
tools.append({
    "name": tool_name,
    "description": description,
    "input_schema": {"type": "object", "properties": {}},
})

# After:
input_schema = _resolve_input_schema(spec)
tools.append({
    "name": tool_name,
    "description": description,
    "input_schema": input_schema,
})
```

Add a helper at the top of the file:

```python
def _resolve_input_schema(spec: "CapabilitySpec") -> dict[str, Any]:
    """Load the declared JSON schema for a capability, falling back to an empty object schema."""
    if not spec.input_schema_ref:
        return {"type": "object", "properties": {}}
    from pathlib import Path
    schema_path = Path("schemas") / f"{spec.input_schema_ref}.json"
    try:
        import json as _json
        return _json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        LOGGER.warning("agent_run: could not load input schema for %s", spec.capability_id)
        return {"type": "object", "properties": {}}
```

This change benefits **all** capabilities, not just `agent.run` — any capability with a declared `input_schema_ref` will now have its properties surfaced to the calling LLM.

### 3. Add a recursion depth guard

Thread a `_recursion_depth` parameter through the call stack to prevent cycles.

**`agent_tools.py` — `agent_run()` signature change:**

```python
def agent_run(
    payload: dict[str, Any],
    provider: LLMProvider,
    *,
    invoke_capability: Callable[[str, dict[str, Any]], dict[str, Any]],
    _recursion_depth: int = 0,
) -> dict[str, Any]:
```

Add a guard at the top of `agent_run()`:

```python
_MAX_RECURSION_DEPTH = 4

if _recursion_depth > _MAX_RECURSION_DEPTH:
    raise ToolExecutionError(
        f"agent_run: recursion depth {_recursion_depth} exceeds limit {_MAX_RECURSION_DEPTH}"
    )
```

**`tool_registry.py` — `_agent_run()` wrapper:**

Pass depth through the `invoke_capability` closure so each recursive call increments it:

```python
def _agent_run(payload: Dict[str, Any], provider: LLMProvider, _recursion_depth: int = 0) -> Dict[str, Any]:
    def _execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "agent_run":
            return _agent_run(arguments, provider, _recursion_depth=_recursion_depth + 1)
        reg = default_registry(http_fetch_enabled=True, llm_enabled=True, llm_provider=provider)
        tool = reg.get(tool_name)
        if tool is None:
            raise ToolExecutionError(f"tool_not_found:{tool_name}")
        return tool.handler(arguments)

    return agent_tools.agent_run(
        payload,
        provider,
        invoke_capability=lambda cap_id, args: mcp_gateway.invoke_capability(
            cap_id, args, execute_tool=_execute_tool,
        ),
        _recursion_depth=_recursion_depth,
    )
```

---

## Files Changed

| File | Change |
|---|---|
| `schemas/agent_run_capability_input.json` | New — JSON schema for `agent.run` inputs |
| `config/capability_registry.yaml` | Set `input_schema_ref: agent_run_capability_input` on `agent.run` |
| `libs/tools/agent_tools.py` | Add `_resolve_input_schema()` helper; use it in tool descriptor loop; add `_recursion_depth` param and guard to `agent_run()` |
| `libs/core/tool_registry.py` | Modify `_agent_run()` to intercept `agent_run` tool calls before `default_registry()` and pass incremented depth |

---

## Behaviour After Changes

| Scenario | Before | After |
|---|---|---|
| Agent calls sub-agent with `goal` | LLM often omits `goal` (no schema) | LLM sees `goal` as required field, passes it |
| Agent calls sub-agent with `allowed_capability_ids` | LLM unaware of field | LLM sees declared array property |
| A → B → A → B cycle | Exhausts max_steps at every level (quadratic calls) | Stopped at depth 5 with a `ToolExecutionError` |
| Non-recursive capabilities | No change (empty schema if no `input_schema_ref`) | Richer schema for capabilities with `input_schema_ref` set |

---

## Non-Goals

- **Shared memory between agents**: out of scope. Context passing between agents in a workflow remains through `$from` step_output bindings on the `result` field.
- **Dynamic `allowed_capability_ids` from the parent agent**: a calling agent cannot grant capabilities it doesn't itself have; enforcement remains in `invoke_capability` via the existing capability allow-list check.
- **UI-level sub-agent configuration**: the workflow studio agent node inspector already exposes `goal` and `max_steps`. `allowed_capability_ids` is injected from the agent definition. No UI changes needed.

---

## Open Questions

1. Should `_MAX_RECURSION_DEPTH` be configurable per agent definition or kept as a global constant?
2. Should the error at max depth be a hard failure (`ToolExecutionError`) or a soft degradation (return a structured error result so the parent agent can handle it)?
3. Should the schema path be resolved relative to the working directory or the package root? Currently all other schema lookups use `Path("schemas")` relative to CWD.
