# ue5-mcp

A production-quality **Model Context Protocol (MCP) server** for controlling and understanding **Unreal Engine 5** from AI agents — Cursor, Claude Desktop, or any MCP-compatible client.

The goal is a complete AI co-pilot for UE5 game development: one that understands your project, generates real assets, debugs real problems, and runs automated tests — all through natural language.

```
You:    "What weapon systems already exist?"
Claude: { "blueprints": ["BP_Pistol", "BP_Rifle", "BP_Shotgun"] }

You:    "Populate this forest with 500 trees, random scale, avoid roads."
Claude: → spawn_foliage() → trees placed, collision generated, LODs configured

You:    "My player falls through the floor."
Claude: Checking collision... capsule... physics... → "Floor mesh collision disabled."
```

---

## Quick Start

**Requirements:** Python 3.10+, [uv](https://docs.astral.sh/uv/)

```bash
cd ue5-mcp
cp .env.example .env
uv sync --dev
uv run ue5-mcp
```

**Mock mode** (no editor required — good for development):

```bash
UE_MOCK_MODE=true uv run ue5-mcp
```

**With a project on disk** (filesystem scanning, no editor needed):

```bash
UE_PROJECT_PATH=/path/to/MyGame/MyGame.uproject uv run ue5-mcp
```

**Connect Cursor:** copy `config/cursor-mcp.example.json` into your Cursor MCP settings and set the absolute path to this repo. See [Cursor MCP docs](https://docs.cursor.com/context/mcp).

**Unreal setup (live editor mode):**

1. Open your project in the UE editor.
2. Enable **Edit → Plugins → Remote Control API** and **Editor Scripting Utilities**.
3. Restart the editor. Default HTTP port is `30010`.
4. Match `UE_HOST` / `UE_HTTP_PORT` in `.env`.

---

## The Platform Vision

This MCP is built as a **layered platform**, not a collection of one-off scripts. Each layer builds on the previous one, and every tool added makes the AI smarter about your project.

```
AI (Claude / Cursor)
        │
        ▼
   Unreal MCP
        │
        ├── Layer 1 · Project Knowledge   ← what exists in the project
        ├── Layer 2 · Environment Tools   ← place and configure things
        ├── Layer 3 · Blueprint Tools     ← generate and edit logic
        ├── Layer 4 · Debugging Tools     ← diagnose and fix problems
        ├── Layer 5 · Testing Tools       ← automated validation
        └── Layer 6 · Safety Layer        ← guardrails on everything
```

---

## Current State

### Tools available now

| Tool | Description |
|------|-------------|
| `ue_ping` | Check connectivity to the Unreal Editor Remote Control API |
| `ue_get_editor_info` | Return basic editor connection info |
| `list_project_assets` | **Return all project assets grouped by category** |
| `list_asset_categories` | Return all supported category keys (for filtering) |

### Resources

| URI | Description |
|-----|-------------|
| `unreal://connection/status` | Live connection status to the editor |
| `unreal://config` | Active server configuration (host, ports, mode) |

### Prompts

| Prompt | Description |
|--------|-------------|
| `explore_level` | Workflow template: inspect current level before making changes |
| `prototype_gameplay` | Workflow template: rapid feature prototyping in UE5 |

---

## Layer 1 · Project Knowledge — *Done*

> **The AI must know what exists before it can act.**

Without this layer, the AI hallucinates asset names, references Blueprints that don't exist, and creates duplicates of things you already have. `list_project_assets` is the foundation every other tool in this platform depends on.

### `list_project_assets`

Returns every asset in the project, grouped by category, with three fallback strategies:

1. **Live editor** — calls `EditorAssetLibrary.ListAssets` + `FindAssetData` via Remote Control for exact UE class names.
2. **Filesystem scan** — walks the `Content/` directory and classifies assets by naming prefix (`SM_`, `BP_`, `MI_`…) and folder hints (`Materials/`, `Maps/`, `Textures/`…).
3. **Mock data** — representative stub assets when no editor or project path is available.

**Example response:**

```json
{
  "project": "MyGame",
  "discovery_method": "filesystem",
  "total_assets": 847,
  "categories": {
    "blueprints": {
      "display_name": "Blueprints",
      "count": 43,
      "assets": [
        { "name": "BP_Pistol",   "game_path": "/Game/Weapons/BP_Pistol" },
        { "name": "BP_Rifle",    "game_path": "/Game/Weapons/BP_Rifle" },
        { "name": "BP_Shotgun",  "game_path": "/Game/Weapons/BP_Shotgun" }
      ]
    },
    "maps": { "count": 3, "assets": [...] },
    "static_meshes": { "count": 156, "assets": [...] }
  }
}
```

**27 categories supported** (extensible — add new ones in `bridge/asset_registry.py`):

Static Meshes · Skeletal Meshes · Skeletons · Physics Assets · Materials · Material Instances · Textures · Blueprints · Anim Blueprints · Widget Blueprints (UMG) · Maps/Levels · Niagara Systems · Niagara Emitters · Particle Systems (Cascade) · Sound Waves · Sound Cues · MetaSounds · Sound Classes/Mixes · Animations · Level Sequences · Data Tables · Data Assets · Curves · Enhanced Input · Landscape · Fonts · Structs & Enums

---

## Layer 2 · Environment Tools — *Planned*

> **Let the AI place, configure, and modify things in the world.**

These tools connect Claude directly to level editing tasks — the kinds of things that take hours of manual work.

### Planned tools

**Actor management**

| Tool | Description |
|------|-------------|
| `list_actors` | Return all actors in the current level with transforms and properties |
| `spawn_actor` | Spawn any Blueprint or native actor at a location |
| `move_actor` | Set actor position, rotation, scale |
| `delete_actor` | Remove an actor (confirm=true required) |
| `set_actor_property` | Set any exposed property on an actor |
| `get_actor_property` | Read a property from a specific actor |
| `find_actors_by_tag` | Search actors by tag or class |
| `select_actors` | Programmatically select actors in the editor |

**Foliage & environment population**

| Tool | Description |
|------|-------------|
| `spawn_foliage` | Place foliage with scale variation, density, and avoidance zones |
| `clear_foliage` | Remove foliage by mesh or region |
| `configure_lod` | Set LOD distances and settings for a mesh |
| `generate_collision` | Auto-generate collision for a static mesh |

**Level management**

| Tool | Description |
|------|-------------|
| `list_levels` | List all levels including sub-levels and World Partition cells |
| `open_level` | Open a map by name or path |
| `save_current_level` | Save the current level |
| `set_world_settings` | Configure gravity, time dilation, and other world settings |

**Landscape & terrain**

| Tool | Description |
|------|-------------|
| `list_landscape_layers` | Return all landscape layers and their materials |
| `paint_landscape_layer` | Apply a layer weight to a landscape region |
| `configure_pcg_graph` | Set parameters on a PCG (Procedural Content Generation) graph |

---

## Layer 3 · Blueprint Tools — *Planned*

> **Let the AI generate and edit game logic — not just content.**

This is where the MCP moves from "assistant" to "co-developer." Claude can create Blueprints, add nodes, wire logic, and set defaults based on plain-language descriptions.

### Planned tools

**Blueprint generation**

| Tool | Description |
|------|-------------|
| `create_blueprint` | Create a new Blueprint class with a parent class |
| `add_variable` | Add a variable to a Blueprint (type, default value, replication) |
| `add_event` | Add a standard event (BeginPlay, Tick, Overlap, etc.) |
| `add_function` | Create a new function inside a Blueprint |
| `add_custom_event` | Add a named custom event with parameters |
| `compile_blueprint` | Trigger a Blueprint compile and return errors |

**Node graph editing** *(requires C++ plugin — see Architecture)*

| Tool | Description |
|------|-------------|
| `add_node` | Add a node to a Blueprint graph by function/event name |
| `connect_pins` | Wire two node pins together |
| `set_node_property` | Set a literal value on a node pin |
| `delete_node` | Remove a node from the graph |
| `find_nodes` | Search a Blueprint graph for nodes by type or name |

**Example — generate a door Blueprint:**

```
Prompt: "Create a door that opens when the player approaches,
         closes after 5 seconds, and plays a sound."

MCP creates:
  BP_Door
   ├── Event Begin Overlap
   ├── Gate node (prevent re-triggering)
   ├── Timeline (rotation 0° → 90°)
   ├── Delay (5.0 seconds)
   ├── Reverse Timeline
   └── Play Sound at Location
```

---

## Layer 4 · Debugging Tools — *Planned*

> **Give the AI the ability to diagnose and fix real problems.**

Instead of copy-pasting logs into chat, the AI can inspect the editor state directly and form conclusions.

### Planned tools

**Collision & physics**

| Tool | Description |
|------|-------------|
| `check_actor_collision` | Inspect collision settings on a specific actor |
| `check_character_capsule` | Validate capsule size vs. mesh bounds |
| `list_physics_bodies` | Return all physics bodies in the level with their settings |
| `visualize_collision` | Toggle collision visualization in the editor |

**Performance**

| Tool | Description |
|------|-------------|
| `get_draw_call_stats` | Return draw call counts from the last frame |
| `get_shader_complexity` | Return average shader complexity for the current view |
| `find_expensive_actors` | Identify actors contributing most to frame cost |
| `list_unbuilt_lighting` | Find meshes with missing or stale lightmap builds |

**Asset validation**

| Tool | Description |
|------|-------------|
| `find_missing_references` | Detect broken asset references across the project |
| `find_oversized_textures` | List textures above a given resolution threshold |
| `validate_blueprint` | Check a Blueprint for compile errors or bad references |
| `list_redirectors` | Find stale asset redirectors that need fixing |

**Log analysis**

| Tool | Description |
|------|-------------|
| `get_output_log` | Retrieve recent Output Log entries, filterable by category |
| `get_message_log` | Retrieve the Message Log (compile errors, load warnings) |
| `clear_output_log` | Clear the Output Log |

**Example — player falling through floor:**

```
Claude: Checking collision settings on floor mesh... disabled.
Claude: Checking character capsule... valid.
Claude: Checking physics scene settings... valid.

Result: "SM_Floor_01 has collision set to NoCollision.
         Change to BlockAll or BlockAllDynamic."
```

---

## Layer 5 · Testing Tools — *Planned*

> **Let the AI run and interpret automated tests.**

Connects the MCP to Unreal's built-in testing infrastructure and headless build pipeline.

### Planned tools

**Functional tests**

| Tool | Description |
|------|-------------|
| `list_automation_tests` | List all tests registered in the project |
| `run_automation_test` | Run a specific test or filter by name |
| `get_test_results` | Return pass/fail results from the last test run |
| `run_all_tests` | Run the full test suite and return a summary |

**PIE (Play In Editor)**

| Tool | Description |
|------|-------------|
| `start_pie` | Launch Play In Editor |
| `stop_pie` | Stop the current PIE session |
| `get_pie_state` | Check whether a PIE session is active |
| `send_console_command` | Execute a console command during PIE |

**Headless builds**

| Tool | Description |
|------|-------------|
| `build_project` | Trigger a full project build via UnrealEditor-Cmd |
| `cook_content` | Cook content for a target platform |
| `run_gauntlet_test` | Execute a Gauntlet automated test |
| `get_build_log` | Retrieve the output from the last build |

---

## Layer 6 · Safety — *Ongoing*

> **The AI is a powerful junior dev — give it the right permissions, not root access.**

Safety features are woven throughout every layer, not bolted on at the end.

| Feature | Status | Description |
|---------|--------|-------------|
| Mock mode | ✅ Done | Full server runs without a live editor (`UE_MOCK_MODE=true`) |
| Graceful fallback | ✅ Done | Three-tier discovery: live editor → filesystem → mock |
| `confirm=true` | Planned | Destructive tools (delete, clear, overwrite) require explicit confirmation |
| Read-only mode | Planned | Server-wide flag that disables all write tools |
| Dry-run mode | Planned | Tools describe what they *would* do without executing |
| Scope limiting | Planned | Restrict tools to a specific folder (e.g. `/Game/Sandbox`) |
| Audit log | Planned | Append-only log of every tool call and its result |

---

## Architecture

```
Cursor / Claude
      │  stdio (MCP)
      ▼
 FastMCP Server (ue5-mcp)
      │
      ├── tools/          ← agent actions
      │    ├── editor.py       (ping, editor info)
      │    ├── assets.py       ← Layer 1 · done
      │    ├── environment.py  ← Layer 2 · planned
      │    ├── blueprints.py   ← Layer 3 · planned
      │    ├── debugging.py    ← Layer 4 · planned
      │    └── testing.py      ← Layer 5 · planned
      │
      ├── resources/      ← read-only context (unreal:// URIs)
      ├── prompts/        ← workflow templates
      │
      └── bridge/         ← transport to Unreal
           ├── client.py          (Remote Control HTTP)
           ├── asset_registry.py  (27-category classification engine)
           └── asset_scanner.py   (filesystem Content/ scanner)
```

**Transport options (bridge layer):**

| Mode | How it works | Best for |
|------|-------------|----------|
| **Remote Control API** | HTTP to editor on port 30010 — built in, no extra code | Actor manipulation, property get/set, Blueprint calls |
| **Editor Python** | MCP triggers Python scripts running inside the editor | Batch pipeline work, asset imports, Sequencer |
| **C++ plugin** *(future)* | Custom plugin inside Unreal with a socket/HTTP listener | Deep Blueprint graph editing, node-level access |
| **Headless / CI** | `UnrealEditor-Cmd` and UAT — no UI | Builds, cooks, automated tests |

---

## Project Layout

```
ue5-mcp/
├── pyproject.toml                    # Dependencies + CLI entry point
├── .env.example                      # Connection settings template
├── config/
│   └── cursor-mcp.example.json       # Sample Cursor MCP config
├── src/ue5_mcp/
│   ├── server.py                     # FastMCP entry — registers all primitives
│   ├── config.py                     # Pydantic settings from environment
│   ├── bridge/
│   │   ├── client.py                 # HTTP client → Unreal Remote Control API
│   │   ├── asset_registry.py         # 27 asset categories + classification engine
│   │   └── asset_scanner.py          # Filesystem Content/ directory scanner
│   ├── tools/
│   │   ├── editor.py                 # ue_ping, ue_get_editor_info
│   │   └── assets.py                 # list_project_assets, list_asset_categories
│   ├── resources/
│   │   └── engine.py                 # unreal://connection/status, unreal://config
│   └── prompts/
│       └── workflows.py              # explore_level, prototype_gameplay
└── tests/
    └── test_server.py                # 28 tests covering registry, scanner, tools
```

---

## Development

```bash
uv sync --dev

# Run tests
uv run --with pytest --with pytest-asyncio python -m pytest tests/ -v

# Debug JSON-RPC with MCP Inspector
npx @modelcontextprotocol/inspector uv run ue5-mcp

# Lint
uv run ruff check src/
```

**Adding a new tool:**

1. Add bridge methods to `bridge/client.py` with mock-mode branches.
2. Create `tools/<layer>.py` with a `register_<layer>_tools(mcp, client)` function.
3. Import and call it in `server.py` → `create_app()`.
4. Add tests to `tests/test_server.py`.

**Adding a new asset category:**

Add one `AssetCategory` entry to `bridge/asset_registry.py`. The classification engine, scanner, mock data lookup, and `list_asset_categories` tool all pick it up automatically.

---

## Roadmap

| Layer | Status |
|-------|--------|
| Layer 1 · Project Knowledge (`list_project_assets`, 27 categories) | ✅ Complete |
| Layer 2 · Environment Tools (actors, foliage, levels, landscape) | 🔲 Planned |
| Layer 3 · Blueprint Tools (generate, edit, compile) | 🔲 Planned |
| Layer 4 · Debugging Tools (collision, performance, logs, validation) | 🔲 Planned |
| Layer 5 · Testing Tools (automation, PIE, headless builds) | 🔲 Planned |
| Layer 6 · Safety Layer (confirm, read-only, dry-run, audit log) | 🔄 Ongoing |
| C++ bridge plugin (deep Blueprint graph editing) | 🔲 Future |

---

## License

MIT — see [LICENSE](LICENSE).
