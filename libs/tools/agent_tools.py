from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from libs.core.llm_provider import LLMProvider, LLMProviderError, LLMRequest
from libs.framework.tool_runtime import ToolExecutionError

LOGGER = logging.getLogger(__name__)

_DEFAULT_MAX_STEPS = 12
_MAX_RECURSION_DEPTH = 4
_AGENT_RUN_CAPABILITY_ID = "agent.run"


def _accumulate_spawned_agents(
    spawned: list[dict[str, Any]],
    cap_id: str,
    result: Any,
) -> None:
    """Bubble up the agent descriptors reported by a recursive agent.run call."""
    if cap_id != _AGENT_RUN_CAPABILITY_ID or not isinstance(result, dict):
        return
    child_agents = result.get("agents")
    if isinstance(child_agents, list):
        spawned.extend(agent for agent in child_agents if isinstance(agent, dict))
_DEFAULT_INSTRUCTIONS = (
    "You are a helpful agent. Think step by step and use your available tools "
    "to achieve the goal. When you have achieved the goal, respond with your final answer."
)

# Sentinel that the text-based ReAct parser looks for
_FINAL_ANSWER_KEY = "final_answer"
_ACTION_KEY = "action"
_INPUT_KEY = "input"


# ─── Text-based ReAct loop (works with any LLMProvider) ───────────────────────

def _build_react_system_prompt(instructions: str, tools: list[dict[str, Any]]) -> str:
    lines = [instructions.strip(), ""]
    if tools:
        lines.append("You have access to the following tools:")
        for tool in tools:
            lines.append(f"  - {tool['name']}: {tool['description']}")
        lines.append("")
        lines.append(
            "When you need to use a tool, respond with ONLY a JSON object in this exact format:\n"
            '{"thought": "<your reasoning>", "action": "<tool_name>", "input": {<tool arguments>}}\n\n'
            "When you have enough information to answer the goal (or no tools are needed), "
            "respond with ONLY a JSON object in this exact format:\n"
            '{"thought": "<your reasoning>", "final_answer": "<your complete answer>"}'
        )
    else:
        lines.append('Respond with ONLY: {"thought": "<reasoning>", "final_answer": "<answer>"}')
    return "\n".join(lines)


def _parse_react_response(text: str) -> dict[str, Any] | None:
    """Extract the outermost JSON object from the model response."""
    text = text.strip()
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    text = re.sub(r"^```(?:\w+)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Find the outermost {...} in the text using brace counting
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict) and (
                            _FINAL_ANSWER_KEY in obj or _ACTION_KEY in obj
                        ):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
    return None


def _agent_run_react_text(
    goal: str,
    instructions: str,
    max_steps: int,
    tools: list[dict[str, Any]],
    cap_id_by_tool_name: dict[str, str],
    provider: LLMProvider,
    invoke_capability: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    system_prompt = _build_react_system_prompt(instructions, tools)
    conversation: list[str] = [f"Goal: {goal.strip()}"]

    steps_taken = 0
    final_text = ""
    tool_calls_made: list[dict[str, Any]] = []
    spawned_agents: list[dict[str, Any]] = []

    while steps_taken <= max_steps:
        full_prompt = "\n\n".join(conversation)
        try:
            response = provider.generate_request(
                LLMRequest(
                    prompt=full_prompt,
                    system_prompt=system_prompt,
                    metadata={"component": "agent_run", "step": steps_taken},
                )
            )
        except Exception as exc:
            raise LLMProviderError(f"agent_run: LLM error at step {steps_taken}: {exc}") from exc

        raw = response.content.strip()
        parsed = _parse_react_response(raw)

        steps_taken += 1  # count every LLM call as a step

        if parsed is None:
            # Unparseable — strip fences and return raw text
            clean = re.sub(r"^```(?:\w+)?\s*\n?", "", raw)
            clean = re.sub(r"\n?```\s*$", "", clean).strip()
            final_text = clean or raw
            break

        thought = parsed.get("thought", "")

        if _FINAL_ANSWER_KEY in parsed:
            answer = parsed[_FINAL_ANSWER_KEY]
            if isinstance(answer, (dict, list)):
                final_text = json.dumps(answer, indent=2, ensure_ascii=False)
            else:
                final_text = str(answer).strip() or raw
            break

        action = parsed.get(_ACTION_KEY, "")
        tool_input = parsed.get(_INPUT_KEY, {})
        if not isinstance(tool_input, dict):
            tool_input = {}

        if not action:
            final_text = raw
            break

        cap_id = cap_id_by_tool_name.get(action)

        if cap_id is None:
            observation = json.dumps({"error": f"unknown_tool:{action}"})
        else:
            try:
                result = invoke_capability(cap_id, tool_input)
                observation = json.dumps(result) if isinstance(result, dict) else str(result)
                tool_calls_made.append({
                    "capability_id": cap_id,
                    "result_summary": observation[:300],
                })
                _accumulate_spawned_agents(spawned_agents, cap_id, result)
            except Exception as exc:  # noqa: BLE001
                observation = json.dumps({"error": str(exc)})
                tool_calls_made.append({
                    "capability_id": cap_id,
                    "result_summary": f"error:{exc}",
                })

        conversation.append(
            f"Thought: {thought}\nAction: {action}\nInput: {json.dumps(tool_input)}\n"
            f"Observation: {observation}"
        )

        if steps_taken >= max_steps:
            # Ask for a final answer given what we know
            conversation.append("You have reached the maximum number of tool calls. Provide your final answer now.")

    return {
        "result": final_text or "Agent completed without generating a final response.",
        "steps_taken": steps_taken,
        "tool_calls": tool_calls_made,
        "spawned_agents": spawned_agents,
    }


# ─── Anthropic native tool_use loop ───────────────────────────────────────────

def _agent_run_anthropic(
    goal: str,
    instructions: str,
    max_steps: int,
    tools: list[dict[str, Any]],
    cap_id_by_tool_name: dict[str, str],
    provider: Any,
    invoke_capability: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    client = provider.client
    model: str = provider.model
    max_output_tokens: int = getattr(provider, "max_output_tokens", 8192)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": goal.strip()}
    ]
    steps_taken = 0
    final_text = ""
    tool_calls_made: list[dict[str, Any]] = []
    spawned_agents: list[dict[str, Any]] = []

    while steps_taken <= max_steps:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens,
            "system": instructions,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:
            raise LLMProviderError(f"agent_run: Anthropic API error: {exc}") from exc

        stop_reason = getattr(response, "stop_reason", None)

        text_parts: list[str] = []
        tool_use_blocks: list[Any] = []
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            elif block_type == "tool_use":
                tool_use_blocks.append(block)

        if text_parts:
            final_text = " ".join(text_parts).strip()

        if stop_reason == "end_turn" or not tool_use_blocks:
            break

        assistant_content: list[dict[str, Any]] = []
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                assistant_content.append({"type": "text", "text": getattr(block, "text", "")})
            elif block_type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                })
        messages.append({"role": "assistant", "content": assistant_content})

        tool_result_content: list[dict[str, Any]] = []
        for tool_block in tool_use_blocks:
            tool_name = getattr(tool_block, "name", "")
            tool_input: dict[str, Any] = getattr(tool_block, "input", {}) or {}
            tool_use_id = getattr(tool_block, "id", "")
            cap_id = cap_id_by_tool_name.get(tool_name)
            steps_taken += 1

            if cap_id is None:
                result_text = json.dumps({"error": f"unknown_tool:{tool_name}"})
            else:
                try:
                    result = invoke_capability(cap_id, tool_input)
                    result_text = json.dumps(result) if isinstance(result, dict) else str(result)
                    tool_calls_made.append({
                        "capability_id": cap_id,
                        "result_summary": result_text[:300],
                    })
                    _accumulate_spawned_agents(spawned_agents, cap_id, result)
                except Exception as exc:  # noqa: BLE001
                    result_text = json.dumps({"error": str(exc)})
                    tool_calls_made.append({
                        "capability_id": cap_id,
                        "result_summary": f"error:{exc}",
                    })

            tool_result_content.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_result_content})

        if steps_taken >= max_steps:
            break

    return {
        "result": final_text or "Agent completed without generating a final response.",
        "steps_taken": steps_taken,
        "tool_calls": tool_calls_made,
        "spawned_agents": spawned_agents,
    }


# ─── Schema resolution ────────────────────────────────────────────────────────

def _resolve_input_schema(spec: Any) -> dict[str, Any]:
    """Load the declared JSON schema for a capability, falling back to an empty object schema."""
    ref = getattr(spec, "input_schema_ref", None)
    if not ref:
        return {"type": "object", "properties": {}}
    schema_path = Path("schemas") / f"{ref}.json"
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        LOGGER.warning("agent_run: could not load input schema for %s", spec.capability_id)
        return {"type": "object", "properties": {}}


# ─── Public entry point ───────────────────────────────────────────────────────

def agent_run(
    payload: dict[str, Any],
    provider: LLMProvider,
    *,
    invoke_capability: Callable[[str, dict[str, Any]], dict[str, Any]],
    _recursion_depth: int = 0,
) -> dict[str, Any]:
    """Generic ReAct-style agentic loop.

    Uses Anthropic native tool_use when the provider is AnthropicProvider;
    falls back to a text-based ReAct loop for any other LLMProvider.

    Payload fields:
      goal                   - what to accomplish (required)
      instructions           - system prompt (optional)
      max_steps              - iteration cap (default 12)
      allowed_capability_ids - capability IDs the agent may call
      agent_id / role        - optional identity for the run agent registry

    The result includes an ``agents`` list: this invocation's descriptor first,
    followed by every recursively spawned sub-agent (flattened). The API
    materialises these into the durable run agent registry on completion, so a
    dynamically spawned agent.run tree becomes visible and attributed.
    """
    if _recursion_depth > _MAX_RECURSION_DEPTH:
        raise ToolExecutionError(
            f"agent_run: recursion depth {_recursion_depth} exceeds limit {_MAX_RECURSION_DEPTH}"
        )

    goal = payload.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ToolExecutionError("Missing goal")

    agent_id = str(payload.get("agent_id") or "").strip() or (
        f"agent-run-d{_recursion_depth}-{uuid.uuid4().hex[:8]}"
    )
    role = str(payload.get("role") or "").strip() or "agent"

    instructions: str = payload.get("instructions") or _DEFAULT_INSTRUCTIONS
    if not isinstance(instructions, str) or not instructions.strip():
        instructions = _DEFAULT_INSTRUCTIONS

    max_steps_raw = payload.get("max_steps") or _DEFAULT_MAX_STEPS
    try:
        max_steps = max(1, min(32, int(max_steps_raw)))
    except (TypeError, ValueError):
        max_steps = _DEFAULT_MAX_STEPS

    raw_cap_ids = payload.get("allowed_capability_ids") or []
    if not isinstance(raw_cap_ids, list):
        raw_cap_ids = []
    allowed_capability_ids: list[str] = [
        c for c in raw_cap_ids if isinstance(c, str) and c.strip()
    ]

    # Build tool descriptors from the capability registry
    from libs.core import capability_registry as cap_registry  # local import to avoid cycles

    registry = cap_registry.load_capability_registry()
    tools: list[dict[str, Any]] = []
    cap_id_by_tool_name: dict[str, str] = {}

    for cap_id in allowed_capability_ids:
        try:
            spec = registry.require(cap_id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("agent_run: capability not found in registry: %s", cap_id)
            continue
        if not spec.enabled:
            continue
        # Tool names must be [a-zA-Z0-9_-], max 64 chars
        tool_name = cap_id.replace(".", "__").replace("/", "__")[:64]
        description = (spec.description or cap_id)[:1024]
        tools.append({
            "name": tool_name,
            "description": description,
            "input_schema": _resolve_input_schema(spec),
        })
        cap_id_by_tool_name[tool_name] = cap_id

    # Prefer native tool_use when the Anthropic SDK client is available
    if hasattr(provider, "client"):
        loop_result = _agent_run_anthropic(
            goal=goal,
            instructions=instructions,
            max_steps=max_steps,
            tools=tools,
            cap_id_by_tool_name=cap_id_by_tool_name,
            provider=provider,
            invoke_capability=invoke_capability,
        )
    else:
        # Universal text-based ReAct fallback
        loop_result = _agent_run_react_text(
            goal=goal,
            instructions=instructions,
            max_steps=max_steps,
            tools=tools,
            cap_id_by_tool_name=cap_id_by_tool_name,
            provider=provider,
            invoke_capability=invoke_capability,
        )

    # This invocation's descriptor, followed by any spawned sub-agents (flattened).
    self_descriptor = {
        "agent_id": agent_id,
        "role": role,
        "depth": _recursion_depth,
        "status": "done",
        "steps_taken": loop_result.get("steps_taken", 0),
        "goal": goal.strip()[:280],
    }
    spawned = loop_result.pop("spawned_agents", []) or []
    loop_result["agents"] = [self_descriptor, *spawned]
    return loop_result
