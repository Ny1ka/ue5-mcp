"""LLM chat logic: bridges incoming messages to the LLM and MCP tool calls."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

try:
    import anthropic as _anthropic

    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _mcp_tool_to_anthropic(tool) -> dict:
    schema = {}
    if hasattr(tool, "inputSchema") and tool.inputSchema:
        schema = tool.inputSchema
    else:
        schema = {"type": "object", "properties": {}}
    return {
        "name": tool.name,
        "description": (tool.description or "").strip(),
        "input_schema": schema,
    }


async def stream_chat(
    messages: list[dict],
    api_key: str,
    model: str,
    max_tokens: int,
    mcp_app,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted strings for the full chat turn, including tool calls."""
    if not _HAS_ANTHROPIC:
        yield _sse({
            "type": "error",
            "message": "Anthropic package not installed. Run: uv add anthropic",
        })
        return

    if not api_key:
        yield _sse({
            "type": "error",
            "message": "No API key configured. Open Settings and add your Anthropic API key.",
        })
        return

    client = _anthropic.AsyncAnthropic(api_key=api_key)

    try:
        mcp_tools = await mcp_app.list_tools()
    except Exception:
        mcp_tools = []

    tool_defs = [_mcp_tool_to_anthropic(t) for t in mcp_tools]

    anthropic_msgs: list[dict] = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    system = (
        "You are an expert Unreal Engine 5 assistant powered by ue5-mcp. "
        "You help users build games, manage assets, place actors, control the editor, "
        "and work with landscapes, foliage, blueprints, and PCG graphs. "
        "Use the available tools to inspect and control the UE5 editor when appropriate. "
        "Be concise and practical. When you perform an action, confirm what you did and "
        "highlight any important details the user should know."
    )

    while True:
        text_so_far = ""
        tool_calls: list = []
        stop_reason = None
        full_content: list = []

        try:
            async with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=anthropic_msgs,
                **({"tools": tool_defs} if tool_defs else {}),
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        text_so_far += event.delta.text
                        yield _sse({"type": "text", "content": event.delta.text})

                final = await stream.get_final_message()
                stop_reason = final.stop_reason
                full_content = list(final.content)

        except _anthropic.AuthenticationError:
            yield _sse({"type": "error", "message": "Invalid API key — check your key in Settings."})
            return
        except _anthropic.RateLimitError:
            yield _sse({"type": "error", "message": "Rate limit reached. Please wait a moment and try again."})
            return
        except _anthropic.APIError as exc:
            yield _sse({"type": "error", "message": f"Anthropic API error: {exc}"})
            return
        except Exception as exc:
            yield _sse({"type": "error", "message": f"Unexpected error: {exc}"})
            return

        for block in full_content:
            if block.type == "tool_use":
                tool_calls.append(block)

        if stop_reason != "tool_use" or not tool_calls:
            break

        # Build the assistant turn (text + tool_use blocks)
        assistant_content: list[dict] = []
        if text_so_far:
            assistant_content.append({"type": "text", "text": text_so_far})
        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            })
        anthropic_msgs.append({"role": "assistant", "content": assistant_content})

        # Execute each tool via the MCP app
        tool_results: list[dict] = []
        for tc in tool_calls:
            yield _sse({"type": "tool_start", "id": tc.id, "name": tc.name, "input": tc.input})
            try:
                result_items = await mcp_app.call_tool(tc.name, tc.input)
                result_text = "\n".join(
                    item.text for item in result_items if hasattr(item, "text")
                )
                if not result_text:
                    result_text = str(result_items)
            except Exception as exc:
                result_text = f"Tool error: {exc}"

            yield _sse({
                "type": "tool_end",
                "id": tc.id,
                "name": tc.name,
                "result": result_text[:2000],
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result_text,
            })

        anthropic_msgs.append({"role": "user", "content": tool_results})
        text_so_far = ""
        tool_calls = []

    yield _sse({"type": "done"})
