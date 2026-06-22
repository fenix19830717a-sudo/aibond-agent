"""Workflow execution engine - executes workflow definitions node by node."""

import operator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Workflow, WorkflowInstance
from app.websocket.manager import ws_manager


# Simple expression evaluator for condition nodes.
# Supported operators: ==, !=, >, <, >=, <=
_CONDITION_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}


class WorkflowEngine:
    """Execute workflow definitions node by node."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(self, workflow_id: str) -> dict:
        """Execute a workflow and return results.

        Loads the workflow definition, creates an instance, then executes
        nodes sequentially following edges. Supports 5 node types:
        trigger, ai, human_review, condition, output.

        Returns a dict with instance_id, status, and node_results.
        """
        # Load workflow definition
        result = await self.db.execute(
            select(Workflow).where(Workflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        if not workflow:
            return {"error": "Workflow not found", "status": "failed"}

        definition = workflow.definition or {}
        nodes = definition.get("nodes", [])
        edges = definition.get("edges", [])

        if not nodes:
            return {"error": "Workflow has no nodes", "status": "failed"}

        # Build node lookup and edge adjacency
        node_map: dict[str, dict] = {}
        for node in nodes:
            node_id = node.get("id", "")
            if node_id:
                node_map[node_id] = node

        # Build adjacency: source_node_id -> list of (target_node_id, edge_data)
        adjacency: dict[str, list[tuple[str, dict]]] = {}
        for edge in edges:
            source = edge.get("source", "")
            target = edge.get("target", "")
            if source and target:
                if source not in adjacency:
                    adjacency[source] = []
                adjacency[source].append((target, edge))

        # Create workflow instance
        instance = WorkflowInstance(
            id=str(__import__("uuid").uuid4()),
            workflow_id=workflow_id,
            status="running",
            context={},
            node_results=[],
        )
        self.db.add(instance)
        await self.db.commit()
        await self.db.refresh(instance)

        # Find the starting node (trigger node)
        start_node_id = self._find_start_node(nodes)
        if not start_node_id:
            instance.status = "failed"
            instance.node_results = instance.node_results or []
            instance.node_results.append({
                "node_id": None,
                "node_type": "system",
                "status": "error",
                "message": "No trigger/start node found",
                "timestamp": str(datetime.now(timezone.utc)),
            })
            await self.db.commit()
            return {
                "instance_id": instance.id,
                "status": instance.status,
                "node_results": instance.node_results,
            }

        # Execute nodes sequentially
        current_node_id = start_node_id
        context: dict[str, Any] = {}
        node_results: list[dict] = []
        max_steps = 50  # Safety limit to prevent infinite loops

        for _ in range(max_steps):
            if not current_node_id or current_node_id not in node_map:
                break

            node = node_map[current_node_id]
            node_data = node.get("data", {})
            node_type = node_data.get("nodeType", "output")
            config = node_data.get("config", {})

            # Update instance current node
            instance.current_node_id = current_node_id
            await self.db.commit()

            # Execute based on node type
            step_result = await self._execute_node(
                node_type=node_type,
                node_id=current_node_id,
                config=config,
                context=context,
                workflow_id=workflow_id,
                instance_id=instance.id,
            )
            node_results.append(step_result)

            # Store output in context
            if step_result.get("output") is not None:
                context[current_node_id] = step_result["output"]

            # Check if execution should stop (human_review or error)
            if step_result.get("status") == "pending_review":
                instance.status = "pending_review"
                instance.context = context
                instance.node_results = node_results
                await self.db.commit()
                return {
                    "instance_id": instance.id,
                    "status": instance.status,
                    "current_node_id": current_node_id,
                    "node_results": node_results,
                }

            if step_result.get("status") == "error":
                instance.status = "failed"
                instance.context = context
                instance.node_results = node_results
                await self.db.commit()
                return {
                    "instance_id": instance.id,
                    "status": instance.status,
                    "current_node_id": current_node_id,
                    "node_results": node_results,
                }

            # Determine next node
            next_node_id = self._get_next_node(
                node_type=node_type,
                node_id=current_node_id,
                step_result=step_result,
                adjacency=adjacency,
                edges_from_node=adjacency.get(current_node_id, []),
            )

            if next_node_id is None:
                # No more nodes to execute - workflow complete
                break

            current_node_id = next_node_id

        # Mark instance as completed
        instance.status = "completed"
        instance.completed_at = datetime.now(timezone.utc)
        instance.context = context
        instance.node_results = node_results
        await self.db.commit()

        return {
            "instance_id": instance.id,
            "status": instance.status,
            "node_results": node_results,
        }

    async def _execute_node(
        self,
        node_type: str,
        node_id: str,
        config: dict,
        context: dict,
        workflow_id: str,
        instance_id: str,
    ) -> dict:
        """Execute a single node and return its result."""
        timestamp = str(datetime.now(timezone.utc))

        if node_type == "trigger":
            return {
                "node_id": node_id,
                "node_type": "trigger",
                "status": "completed",
                "output": {"triggered": True, "timestamp": timestamp},
                "timestamp": timestamp,
            }

        elif node_type == "ai":
            # Send task_assign to the configured agent via ws_manager
            agent_id = config.get("agent_id")
            task_prompt = config.get("prompt", "")
            task_title = config.get("title", "Workflow AI Task")

            if agent_id:
                assign_payload = {
                    "type": "task_assign",
                    "workflow_id": workflow_id,
                    "instance_id": instance_id,
                    "node_id": node_id,
                    "title": task_title,
                    "description": task_prompt,
                    "priority": config.get("priority", "normal"),
                    "context": context,
                    "from_workflow": True,
                }
                await ws_manager.send_to_agent(agent_id, assign_payload)

            return {
                "node_id": node_id,
                "node_type": "ai",
                "status": "completed",
                "agent_id": agent_id,
                "output": {"task_sent": True, "agent_id": agent_id, "prompt": task_prompt},
                "timestamp": timestamp,
            }

        elif node_type == "human_review":
            # Set instance status to pending_review (handled by caller)
            return {
                "node_id": node_id,
                "node_type": "human_review",
                "status": "pending_review",
                "output": {"review_required": True},
                "timestamp": timestamp,
            }

        elif node_type == "condition":
            # Evaluate a simple expression and return the result
            expression = config.get("expression", "")
            evaluation = self._evaluate_condition(expression, context)

            return {
                "node_id": node_id,
                "node_type": "condition",
                "status": "completed",
                "output": {"expression": expression, "result": evaluation},
                "condition_result": evaluation,
                "timestamp": timestamp,
            }

        elif node_type == "output":
            # Store the result in the instance
            output_value = config.get("value", context)
            return {
                "node_id": node_id,
                "node_type": "output",
                "status": "completed",
                "output": output_value,
                "timestamp": timestamp,
            }

        else:
            return {
                "node_id": node_id,
                "node_type": node_type,
                "status": "error",
                "message": f"Unknown node type: {node_type}",
                "timestamp": timestamp,
            }

    def _find_start_node(self, nodes: list[dict]) -> str | None:
        """Find the trigger/start node in the workflow definition."""
        for node in nodes:
            node_data = node.get("data", {})
            node_type = node_data.get("nodeType", "")
            if node_type == "trigger":
                return node.get("id")
        # Fallback: return the first node if no trigger found
        if nodes:
            return nodes[0].get("id")
        return None

    def _get_next_node(
        self,
        node_type: str,
        node_id: str,
        step_result: dict,
        adjacency: dict,
        edges_from_node: list[tuple[str, dict]],
    ) -> str | None:
        """Determine the next node to execute based on edges."""
        if not edges_from_node:
            return None

        if node_type == "condition":
            # For condition nodes, route based on the condition result
            condition_result = step_result.get("condition_result", False)
            for target_id, edge_data in edges_from_node:
                edge_handle = edge_data.get("data", {}).get("handleId", "")
                # "true" handle for True branch, "false" handle for False branch
                if condition_result and "true" in str(edge_handle).lower():
                    return target_id
                if not condition_result and "false" in str(edge_handle).lower():
                    return target_id
            # Fallback: return first edge target
            return edges_from_node[0][0] if edges_from_node else None

        # For all other node types, follow the first outgoing edge
        return edges_from_node[0][0] if edges_from_node else None

    def _evaluate_condition(self, expression: str, context: dict) -> bool:
        """Evaluate a simple condition expression against the context.

        Supports patterns like:
        - "node_id.field == value"
        - "node_id.field != value"
        - "node_id.field > value"
        - "node_id.field < value"
        - Simple boolean: "true" / "false"
        """
        expression = expression.strip().lower()

        # Simple boolean literals
        if expression in ("true", "1", "yes"):
            return True
        if expression in ("false", "0", "no"):
            return False

        # Try to parse "key op value" pattern
        for op_str, op_func in _CONDITION_OPS.items():
            if op_str in expression:
                parts = expression.split(op_str, 1)
                if len(parts) == 2:
                    left_key = parts[0].strip().strip("'\"")
                    right_value = parts[1].strip().strip("'\"")

                    # Resolve left value from context
                    left_value = self._resolve_context_value(left_key, context)

                    # Try numeric comparison
                    try:
                        left_num = float(left_value) if not isinstance(left_value, (int, float)) else left_value
                        right_num = float(right_value)
                        return op_func(left_num, right_num)
                    except (ValueError, TypeError):
                        # Fall back to string comparison
                        return op_func(str(left_value), right_value)

        # Default: try truthy evaluation
        return bool(expression)

    def _resolve_context_value(self, key: str, context: dict) -> Any:
        """Resolve a dotted key from the context dict.

        E.g., "node1.output" looks up context["node1"]["output"].
        """
        parts = key.split(".")
        value = context
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return key  # Return raw key if not found
        return value
