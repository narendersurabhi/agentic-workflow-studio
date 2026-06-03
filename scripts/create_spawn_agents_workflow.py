#!/usr/bin/env python3
"""Create a published workflow that spawns agents at runtime via ``agent.run``.

The workflow is a single ``agent.run`` orchestrator node whose
``allowed_capability_ids`` *includes ``agent.run`` itself* — that is what lets
the orchestrator recursively spawn specialised sub-agents. Each spawned agent
is materialised into the run's durable agent registry on completion (visible in
the Studio Agents panel and attributed in the blackboard / artifacts).

Usage:
    # against a running API (default http://localhost:8000)
    python scripts/create_spawn_agents_workflow.py
    # create AND launch a run
    API_BASE_URL=http://localhost:8000 python scripts/create_spawn_agents_workflow.py --run

The draft this builds is importable for tests via build_spawn_agents_draft().
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any


# Capabilities the orchestrator agent may call. Including "agent.run" is what
# makes this a spawn-agents workflow: the agent can delegate to sub-agents.
ORCHESTRATOR_ALLOWED_CAPABILITIES = [
    "agent.run",                  # spawn specialised sub-agents (recursive)
    "filesystem.workspace.list",  # inspect the workspace
    "llm.text.generate",          # reason / synthesise
    "memory.read",                # recall shared run memory
]

ORCHESTRATOR_INSTRUCTIONS = (
    "You are an orchestrator agent. Break the goal into focused sub-tasks and "
    "delegate each to a specialised sub-agent by calling agent.run with a "
    "narrow goal and only the capabilities that sub-task needs. Use the "
    "blackboard to share findings, avoid duplicating work, and synthesise the "
    "sub-agents' results into a single final answer."
)

ORCHESTRATOR_GOAL = (
    "Inspect the workspace, delegate research and drafting to specialised "
    "sub-agents, then synthesise their results into a concise summary."
)


def build_spawn_agents_draft() -> dict[str, Any]:
    """The workflow draft: one agent.run orchestrator node that spawns sub-agents."""
    return {
        "summary": "Agent Orchestrator (spawns sub-agents)",
        "nodes": [
            {
                "id": "orchestrator",
                "taskName": "OrchestratorAgent",
                "capabilityId": "agent.run",
                "nodeKind": "agent",
                "outputPath": "result",
                "bindings": {
                    "goal": {"kind": "literal", "value": ORCHESTRATOR_GOAL},
                    "instructions": {"kind": "literal", "value": ORCHESTRATOR_INSTRUCTIONS},
                    "allowed_capability_ids": {
                        "kind": "literal",
                        "value": list(ORCHESTRATOR_ALLOWED_CAPABILITIES),
                    },
                    "max_steps": {"kind": "literal", "value": 8},
                    "role": {"kind": "literal", "value": "orchestrator"},
                },
            }
        ],
        "edges": [],
    }


def build_definition_payload(user_id: str | None = None) -> dict[str, Any]:
    return {
        "title": "Agent Orchestrator",
        "goal": ORCHESTRATOR_GOAL,
        "user_id": user_id,
        "context_json": {"user_id": user_id} if user_id else {},
        "draft": build_spawn_agents_draft(),
    }


def _post(base_url: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # surface the API error body
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"POST {path} failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach API at {base_url}: {exc.reason}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a spawn-agents workflow.")
    parser.add_argument("--run", action="store_true", help="Also launch a run of the published version.")
    parser.add_argument("--user-id", default=os.getenv("WORKFLOW_USER_ID") or None)
    args = parser.parse_args()
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")

    definition = _post(base_url, "/workflows/definitions", build_definition_payload(args.user_id))
    print(f"Created workflow definition: {definition['id']} ({definition.get('title')})")

    version = _post(base_url, f"/workflows/definitions/{definition['id']}/publish", {})
    print(f"Published version: {version['id']}")

    if args.run:
        run = _post(base_url, f"/workflows/versions/{version['id']}/run", {"priority": 1})
        print(f"Launched run: {run.get('id')} (job {run.get('job_id')})")
        print("Spawned agents will appear in the run's Agents panel once the orchestrator completes.")


if __name__ == "__main__":
    main()
