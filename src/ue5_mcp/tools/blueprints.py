"""Blueprint tools — Layer 3 of the Unreal MCP platform.

This module lets an AI agent generate and edit Blueprint logic — creating classes,
adding variables and events, defining functions, and compiling results.

Tools are organised into two groups:

  Group 1 · Blueprint Generation (no graph-node access required)
    create_blueprint, add_variable, add_event, add_function,
    add_custom_event, compile_blueprint, get_blueprint_info

  Group 2 · Graph Inspection & Editing (read-only node queries + simple edits)
    find_blueprint_nodes

All tools:
  • Work in mock mode (UE_MOCK_MODE=true) — no live editor required
  • Return structured JSON via client.format_json()
  • Handle UEConnectionError gracefully
  • Respect UE_READ_ONLY=true (write tools return an error in read-only mode)
  • Are audited via bridge/audit.py

Live mode for node graph editing (add_node, connect_pins, delete_node) requires
the Python Script Plugin or a custom C++ plugin — see the README architecture
section.  The query tool (find_blueprint_nodes) works in live mode via Python.
"""

from __future__ import annotations

import datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge import audit
from ue5_mcp.bridge.client import UEClient, UEConnectionError


def register_blueprint_tools(mcp: FastMCP, client: UEClient) -> None:
    """Register all Layer 3 Blueprint tools on the MCP server."""

    settings = client.settings

    # ==================================================================
    # GROUP 1 · BLUEPRINT GENERATION
    # ==================================================================

    @mcp.tool()
    async def create_blueprint(
        blueprint_name: Annotated[
            str,
            "Asset name for the new Blueprint, e.g. 'BP_MyDoor'. "
            "Do NOT include a path — use save_path for that.",
        ],
        parent_class: Annotated[
            str,
            "UE base class to inherit from. Common values: "
            "'Actor', 'Character', 'Pawn', 'ActorComponent', "
            "'GameMode', 'GameInstance', 'PlayerController', 'AIController', "
            "'UserWidget', 'AnimInstance'. Use the exact C++ class name.",
        ] = "Actor",
        save_path: Annotated[
            str,
            "Game path of the folder where the asset should be saved. "
            "Example: '/Game/Blueprints/Characters'. "
            "The folder will be created if it does not exist.",
        ] = "/Game/Blueprints",
    ) -> str:
        """Create a new Blueprint class asset in the project.

        This is the starting point for Blueprint generation workflows.  After
        creating the Blueprint, use add_variable, add_event, add_function, and
        compile_blueprint to flesh it out.

        Example workflow:
          1. create_blueprint('BP_Door', 'Actor', '/Game/Props')
          2. add_variable('BP_Door', 'IsOpen', 'Boolean')
          3. add_event('/Game/Props/BP_Door', 'ReceiveBeginPlay')
          4. compile_blueprint('/Game/Props/BP_Door')

        Returns the full game path of the created asset.
        """
        if settings.ue_read_only:
            return client.format_json(_error("create_blueprint", "Server is in read-only mode."))

        if not blueprint_name.startswith("BP_"):
            pass  # UE convention, not enforced — just document it.

        if not save_path.startswith("/Game/"):
            return client.format_json(
                _error(
                    "create_blueprint",
                    f"save_path must start with '/Game/', got '{save_path}'.",
                )
            )

        try:
            result = await client.create_blueprint(parent_class, blueprint_name, save_path)
            payload: dict[str, Any] = {
                **result,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "create_blueprint",
                               {"blueprint_name": blueprint_name, "parent_class": parent_class,
                                "save_path": save_path}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("create_blueprint", str(exc)))

    @mcp.tool()
    async def add_variable(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset. "
            "Example: '/Game/Blueprints/BP_Door'. "
            "Use list_project_assets(category_filter='blueprints') to find valid paths.",
        ],
        variable_name: Annotated[
            str,
            "Identifier for the variable, e.g. 'Health', 'IsOpen', 'MoveSpeed'. "
            "Use PascalCase for Blueprint conventions.",
        ],
        variable_type: Annotated[
            str,
            "UE type name. Supported: 'Boolean', 'Integer', 'Float', 'String', "
            "'Name', 'Text', 'Vector', 'Rotator', 'Transform', 'Actor', 'Object'. "
            "Default: 'Float'.",
        ] = "Float",
        default_value: Annotated[
            str,
            "Default value as a string, e.g. '100.0', 'true', 'Hello'. "
            "Leave empty to use the type's zero value.",
        ] = "",
        is_replicated: Annotated[
            bool,
            "Replicate this variable to all clients in multiplayer. "
            "Required for variables that affect gameplay state. Default false.",
        ] = False,
        is_instance_editable: Annotated[
            bool,
            "Expose this variable in the Details panel so it can be overridden "
            "per-actor instance in the level. Default true.",
        ] = True,
    ) -> str:
        """Add a variable to an existing Blueprint.

        Variables store data within a Blueprint instance.  After adding a variable,
        use compile_blueprint to verify the Blueprint is still valid.

        Common patterns:
          • Health system:  add_variable('BP_Enemy', 'Health', 'Float', '100.0', is_replicated=True)
          • Toggle state:   add_variable('BP_Door', 'IsOpen', 'Boolean', 'false')
          • Speed config:   add_variable('BP_Vehicle', 'MaxSpeed', 'Float', '1200.0',
                                         is_instance_editable=True)
        """
        if settings.ue_read_only:
            return client.format_json(_error("add_variable", "Server is in read-only mode."))

        if not blueprint_path.startswith("/Game/"):
            return client.format_json(
                _error(
                    "add_variable",
                    f"blueprint_path must start with '/Game/', got '{blueprint_path}'.",
                )
            )

        valid_types = {
            "Boolean", "Integer", "Float", "String", "Name", "Text",
            "Vector", "Rotator", "Transform", "Actor", "Object",
        }
        if variable_type not in valid_types:
            return client.format_json(
                _error(
                    "add_variable",
                    f"Unknown variable_type '{variable_type}'. "
                    f"Valid types: {', '.join(sorted(valid_types))}.",
                )
            )

        try:
            result = await client.add_blueprint_variable(
                blueprint_path,
                variable_name,
                variable_type,
                default_value,
                is_replicated,
                is_instance_editable,
            )
            payload: dict[str, Any] = {
                **result,
                "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "add_variable",
                               {"blueprint_path": blueprint_path, "variable_name": variable_name,
                                "variable_type": variable_type}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("add_variable", str(exc)))

    @mcp.tool()
    async def add_event(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset.",
        ],
        event_name: Annotated[
            str,
            "UE event function name. Standard events:\n"
            "  'ReceiveBeginPlay'     — Event BeginPlay\n"
            "  'ReceiveEndPlay'       — Event EndPlay\n"
            "  'ReceiveTick'          — Event Tick\n"
            "  'ReceiveActorBeginOverlap' — Actor Begin Overlap\n"
            "  'ReceiveActorEndOverlap'   — Actor End Overlap\n"
            "  'ReceiveHit'           — Event Hit\n"
            "  'ReceiveAnyDamage'     — Take Any Damage\n"
            "  'ReceiveDestroyed'     — Actor Destroyed\n"
            "Use the exact UE function name (case-sensitive).",
        ],
    ) -> str:
        """Add a standard event override to a Blueprint's EventGraph.

        Events are the entry points for Blueprint logic.  The most common are
        ReceiveBeginPlay (runs once when the actor spawns) and ReceiveTick
        (runs every frame).  After adding an event, use add_function to wire
        logic to it.

        Note: Calling this on BeginPlay when a BeginPlay event already exists
        is a no-op in live mode.
        """
        if settings.ue_read_only:
            return client.format_json(_error("add_event", "Server is in read-only mode."))

        if not blueprint_path.startswith("/Game/"):
            return client.format_json(
                _error("add_event", "blueprint_path must start with '/Game/'.")
            )

        try:
            result = await client.add_blueprint_event(blueprint_path, event_name)
            payload: dict[str, Any] = {
                **result,
                "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "add_event",
                               {"blueprint_path": blueprint_path, "event_name": event_name}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("add_event", str(exc)))

    @mcp.tool()
    async def add_function(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset.",
        ],
        function_name: Annotated[
            str,
            "Name of the new function, e.g. 'Die', 'OpenDoor', 'CalculateDamage'. "
            "Use PascalCase for Blueprint conventions.",
        ],
        description: Annotated[
            str,
            "Tooltip / documentation comment for the function. "
            "Shown in the editor when the function node is hovered.",
        ] = "",
        is_pure: Annotated[
            bool,
            "Pure functions execute without exec pins — they are evaluated on-demand "
            "like getters.  Use for read-only calculations. Default false.",
        ] = False,
        access_specifier: Annotated[
            str,
            "Visibility: 'public' (callable from outside), 'protected' (subclasses only), "
            "'private' (this Blueprint only). Default 'public'.",
        ] = "public",
    ) -> str:
        """Add a user-defined function graph to a Blueprint.

        Functions encapsulate reusable logic.  After adding a function, use
        add_custom_event to create entry points or wire it to events in the
        EventGraph.

        Common patterns:
          • Game logic: add_function('BP_Enemy', 'Die')
          • Getter:     add_function('BP_Door', 'IsLocked', is_pure=True)
          • Helper:     add_function('BP_Weapon', 'CalculateDamage', access_specifier='private')
        """
        if settings.ue_read_only:
            return client.format_json(_error("add_function", "Server is in read-only mode."))

        valid_access = {"public", "protected", "private"}
        if access_specifier not in valid_access:
            return client.format_json(
                _error(
                    "add_function",
                    f"access_specifier must be one of: {', '.join(sorted(valid_access))}.",
                )
            )

        try:
            result = await client.add_blueprint_function(
                blueprint_path, function_name, description, is_pure, access_specifier
            )
            payload: dict[str, Any] = {
                **result,
                "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "add_function",
                               {"blueprint_path": blueprint_path,
                                "function_name": function_name}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("add_function", str(exc)))

    @mcp.tool()
    async def add_custom_event(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset.",
        ],
        event_name: Annotated[
            str,
            "Name of the custom event, e.g. 'OnHealthChanged', 'OnDeath', 'OnPickup'. "
            "Custom events can be called programmatically or from other Blueprints. "
            "Use PascalCase.",
        ],
        parameters: Annotated[
            str,
            "JSON array of parameter definitions. Each element: "
            "{\"name\": \"ParamName\", \"type\": \"Float\"}. "
            "Use the same type names as add_variable. "
            "Example: '[{\"name\": \"NewHealth\", \"type\": \"Float\"}, "
            "{\"name\": \"MaxHealth\", \"type\": \"Float\"}]'. "
            "Leave empty ('[]') for no parameters.",
        ] = "[]",
    ) -> str:
        """Add a named custom event with parameters to a Blueprint.

        Custom events are callable entry points — they can be triggered by
        other Blueprints, animation notifies, or code.  They differ from
        standard events in that they are named, dispatched explicitly, and
        can carry parameters.

        Example: add_custom_event('/Game/BP_Enemy', 'OnHealthChanged',
                                  '[{"name": "NewHealth", "type": "Float"}]')
        """
        import json as _json

        if settings.ue_read_only:
            return client.format_json(_error("add_custom_event", "Server is in read-only mode."))

        try:
            params_list: list[dict[str, str]] = _json.loads(parameters)
        except _json.JSONDecodeError as exc:
            return client.format_json(
                _error("add_custom_event", f"parameters is not valid JSON: {exc}")
            )

        try:
            result = await client.add_blueprint_custom_event(
                blueprint_path, event_name, params_list
            )
            payload: dict[str, Any] = {
                **result,
                "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "add_custom_event",
                               {"blueprint_path": blueprint_path,
                                "event_name": event_name,
                                "parameter_count": len(params_list)}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("add_custom_event", str(exc)))

    @mcp.tool()
    async def compile_blueprint(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset. "
            "Example: '/Game/Characters/BP_EnemyBase'. "
            "Use list_project_assets(category_filter='blueprints') to discover paths.",
        ],
    ) -> str:
        """Trigger a Blueprint compile and return errors and warnings.

        Always compile after making structural changes (adding variables,
        events, or functions) to catch problems early.

        Returns:
          • error_count / warning_count — number of issues
          • messages — list of compiler messages with severity and location
          • compiled — whether the compile succeeded without errors

        If compile fails, fix the reported errors and call compile_blueprint
        again to confirm the fix.
        """
        if not blueprint_path.startswith("/Game/"):
            return client.format_json(
                _error("compile_blueprint", "blueprint_path must start with '/Game/'.")
            )

        try:
            result = await client.compile_blueprint(blueprint_path)
            payload: dict[str, Any] = {
                **result,
                "compiled_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "compile_blueprint",
                               {"blueprint_path": blueprint_path}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("compile_blueprint", str(exc)))

    @mcp.tool()
    async def get_blueprint_info(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset. "
            "Example: '/Game/Characters/BP_EnemyBase'.",
        ],
    ) -> str:
        """Return metadata about an existing Blueprint.

        Reports:
          • parent_class — the UE class this Blueprint inherits from
          • variables    — list of member variables with types and defaults
          • functions    — user-defined functions
          • events       — custom events
          • has_compile_errors — whether the last compile succeeded

        Use this before editing a Blueprint to understand what already exists,
        avoiding duplicate variables or conflicting events.
        """
        if not blueprint_path.startswith("/Game/"):
            return client.format_json(
                _error("get_blueprint_info", "blueprint_path must start with '/Game/'.")
            )

        try:
            result = await client.get_blueprint_info(blueprint_path)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_blueprint_info", str(exc)))

    # ==================================================================
    # GROUP 2 · GRAPH INSPECTION
    # ==================================================================

    @mcp.tool()
    async def find_blueprint_nodes(
        blueprint_path: Annotated[
            str,
            "Full /Game/... path to the Blueprint asset.",
        ],
        graph_name: Annotated[
            str,
            "Name of the graph to search. Use 'EventGraph' for the main event graph "
            "or the exact name of a function graph (e.g. 'Die', 'OpenDoor').",
        ] = "EventGraph",
        search_term: Annotated[
            str,
            "Substring to match against node titles and type names. "
            "Examples: 'Print', 'BeginPlay', 'Delay', 'Branch'. "
            "Leave empty to return all nodes in the graph.",
        ] = "",
    ) -> str:
        """Search a Blueprint graph for nodes by function name or type.

        Returns each matching node with its position in the graph, pin names,
        and type.  Use this to understand what logic exists before adding or
        modifying nodes.

        Example: find_blueprint_nodes('/Game/BP_Door', 'EventGraph', 'Overlap')
        returns all Overlap nodes, helping you understand the existing interaction logic.

        Note: Node editing (add_node, connect_pins, delete_node) requires the
        Python Script Plugin or a custom C++ plugin — see README Architecture.
        """
        if not blueprint_path.startswith("/Game/"):
            return client.format_json(
                _error("find_blueprint_nodes", "blueprint_path must start with '/Game/'.")
            )

        try:
            result = await client.find_blueprint_nodes(blueprint_path, graph_name, search_term)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock graph data. Connect a live editor for real node information."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("find_blueprint_nodes", str(exc)))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _error(tool: str, message: str) -> dict[str, Any]:
    return {
        "error": message,
        "tool": tool,
        "success": False,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
