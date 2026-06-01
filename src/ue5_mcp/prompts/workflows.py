"""Workflow prompt templates — guide the agent through multi-step UE tasks."""

from mcp.server.fastmcp import FastMCP


def register_workflow_prompts(mcp: FastMCP) -> None:
    @mcp.prompt()
    def explore_level() -> str:
        """Template for inspecting the current level before making changes."""
        return """You are helping develop a game in Unreal Engine 5.

1. Call `ue_ping` to verify the editor is connected.
2. Read `unreal://connection/status` for connection details.
3. Before spawning or moving actors, describe what exists and what you plan to change.
4. Prefer small, reversible edits; confirm destructive actions with the user.

Ask the user which level or feature they are working on if context is missing."""

    @mcp.prompt()
    def prototype_gameplay(feature: str = "movement") -> str:
        """Template for rapid gameplay prototyping in UE5."""
        return f"""Prototype the gameplay feature: {feature}

Suggested approach:
1. Identify existing actors/Blueprints involved (use tools you add for listing actors).
2. Propose minimal Blueprint or C++ changes.
3. Use PIE (Play In Editor) testing steps the user can run manually until you add PIE tools.
4. List follow-up polish items separately from the MVP.

Keep scope small enough to test in one editor session."""
