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

You:    "Design a FPS bomb site map similar to Ascent on Valorant."
Claude: → translate_style_reference() → plan_environment() → apply_environment_template()
        → build_structure() × N → scatter_assets() → assign_material() → apply_lighting_preset()
        → check_sightlines() → run_correction_pass() → generate_build_report()
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
        ├── Layer 1 · Project Knowledge      ← what exists in the project
        ├── Layer 2 · Environment Tools      ← place and configure things
        ├── Layer 3 · Blueprint Tools        ← generate and edit logic
        ├── Layer 4 · Debugging Tools        ← diagnose and fix problems
        ├── Layer 5 · Testing Tools          ← automated validation
        ├── Layer 6 · Safety Layer           ← guardrails on everything
        └── Environment Building System 🔄  ← full level authoring pipeline
             ├── Core Authoring  (materials, lighting, splines, scattering)
             ├── Composition     (structures, roads, zone population)
             └── Intelligence    (planner, templates, reference translation,
                                  spatial validation, auto-fix, build reports)
```

---

## Current State

**58 tools across 5 layers.** All work in mock mode (`UE_MOCK_MODE=true`). Layer 6 safety is in the server core.

### Layer 1 tools

| Tool | Description |
|------|-------------|
| `ue_ping` | Check connectivity to the Unreal Editor Remote Control API |
| `ue_get_editor_info` | Return basic editor connection info |
| `list_project_assets` | Return all project assets grouped by category |
| `list_asset_categories` | Return all supported category keys (for filtering) |

### Layer 2 tools

**Actor Management**

| Tool | Description |
|------|-------------|
| `list_actors` | Return all actors in the current level with transforms and metadata |
| `spawn_actor` | Spawn any Blueprint or native actor at a world transform |
| `move_actor` | Set actor location, rotation, or scale |
| `delete_actor` | Remove an actor (dry_run=true supported) |
| `set_actor_property` | Set any Remote Control-exposed property on an actor |
| `get_actor_property` | Read a property from a specific actor |
| `find_actors_by_tag` | Search actors by tag, class, or display name |
| `select_actors` | Programmatically select actors in the editor viewport |

**Level Management**

| Tool | Description |
|------|-------------|
| `list_levels` | List all levels including sub-levels and World Partition awareness |
| `open_level` | Open a map by /Game/... path |
| `save_current_level` | Save the current level |
| `set_world_settings` | Configure gravity, time dilation, and kill-Z |

**Foliage & Environment Population**

| Tool | Description |
|------|-------------|
| `spawn_foliage` | Place foliage with density, scale variation, seeded randomisation |
| `clear_foliage` | Remove foliage by mesh type or region |
| `configure_lod` | Set LOD screen-size thresholds for a StaticMesh |
| `generate_collision` | Auto-generate collision for a StaticMesh asset |

**Landscape & PCG**

| Tool | Description |
|------|-------------|
| `list_landscape_layers` | Return all landscape layers and their material assignments |
| `paint_landscape_layer` | Apply layer weight to a landscape region |
| `configure_pcg_graph` | Read and update exposed parameters on a PCG Graph Component |

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

## Layer 2 · Environment Tools — *Done*

> **Let the AI place, configure, and modify things in the world.**

These tools connect Claude directly to level editing tasks — the kinds of things that take hours of manual work.  All 25 tools work in mock mode (`UE_MOCK_MODE=true`) with no live editor required.

### Architecture

```
tools/environment.py          ← 25 MCP tool definitions
bridge/client.py              ← UE Remote Control API calls + mock implementations
```

**Transport strategy per operation type:**

| Operation type | Transport |
|----------------|-----------|
| Actor list / query / select | `EditorActorSubsystem` via Remote Control |
| Actor spawn | `EditorLevelLibrary.SpawnActorFromObject` via Remote Control |
| Actor move / scale / rotate | `K2_SetActorLocation` / `K2_SetActorRotation` / `SetActorScale3D` on actor object |
| Actor property read/write | `/remote/object/property` with READ/WRITE access |
| Level load / save | `EditorLevelLibrary.LoadLevel` / `SaveCurrentLevel` via Remote Control |
| World settings | `/remote/object/property` on WorldSettings actor |
| Foliage / collision / LOD | Python Script Plugin (`ExecutePythonCommand`) — editor Python API |
| Landscape / PCG | Python Script Plugin — landscape weight and PCG component APIs |

### Phase 1 · Actor Management

#### `list_actors`

Returns all actors in the current level. Supports optional filtering by class, folder path, and hidden state.

```json
{
  "actors": [
    {
      "name": "BP_EnemyBase_0",
      "class": "BP_EnemyBase_C",
      "location": {"x": 500.0, "y": 300.0, "z": 0.0},
      "rotation": {"pitch": 0.0, "yaw": 180.0, "roll": 0.0},
      "scale":    {"x": 1.0,   "y": 1.0,   "z": 1.0},
      "tags": ["Enemy", "AI"],
      "folder_path": "Actors/Enemies",
      "level": "PersistentLevel",
      "is_selected": false,
      "is_hidden": false
    }
  ],
  "total": 10,
  "level": "L_TestLevel"
}
```

**Example prompts:**

```
"What actors are currently in the level?"
"List all lights in the level."
"Show me every actor in the Environment/Rocks folder."
```

#### `spawn_actor`

Spawns a Blueprint or native actor at a world transform.

```json
{
  "spawned_actor": "BP_Enemy_mock",
  "object_path": "/Game/Maps/L_TestLevel.L_TestLevel:PersistentLevel.BP_Enemy_mock",
  "asset_path":  "/Game/Characters/BP_EnemyBase.BP_EnemyBase",
  "transform": {
    "location": {"x": 500.0, "y": 0.0, "z": 0.0},
    "rotation": {"pitch": 0.0, "yaw": 90.0, "roll": 0.0},
    "scale":    {"x": 1.0, "y": 1.0, "z": 1.0}
  }
}
```

**Example prompts:**

```
"Spawn 10 BP_Enemy actors around the player start location."
"Place a BP_Door_Automatic at (500, 0, 0) facing north."
```

#### `move_actor`

Moves, rotates, or scales an actor. Returns before/after transforms.

```json
{
  "actor": "SM_Rock_01_0",
  "success": true,
  "before": {"location": {"x": 1200.0, "y": -800.0, "z": 0.0}, "...": "..."},
  "after":  {"location": {"x": 1200.0, "y": -800.0, "z": 200.0}, "...": "..."}
}
```

**Example prompts:**

```
"Move all PointLight actors upward by 200 units."
"Rotate SM_Rock_01_0 so its yaw is 45 degrees."
```

#### `delete_actor`, `set_actor_property`, `get_actor_property`, `find_actors_by_tag`, `select_actors`

Standard actor manipulation tools.  All support dry_run or partial matching.  See tool docstrings for full parameter descriptions.

---

### Phase 2 · Level Management

#### `list_levels`

Returns persistent + streaming sub-levels with load/visibility/dirty state and World Partition flag.

```json
{
  "levels": [
    {"name": "PersistentLevel", "package_path": "/Game/Maps/L_TestLevel",
     "is_persistent": true, "is_loaded": true, "is_dirty": false}
  ],
  "current_world": "/Game/Maps/L_TestLevel",
  "world_partition_enabled": false
}
```

#### `open_level`, `save_current_level`

```
"Open Arena_Map and save it."
→ open_level('/Game/Maps/L_Arena') → save_current_level()
```

#### `set_world_settings`

```json
{
  "applied": ["gravity_z", "game_time_dilation"],
  "before": {"gravity_z": -980.0, "game_time_dilation": 1.0},
  "after":  {"gravity_z": -490.0, "game_time_dilation": 0.5}
}
```

**Example prompts:**

```
"Set gravity to half of normal."
"Enable slow-motion by setting time dilation to 0.3."
```

---

### Phase 3 · Foliage Systems

#### `spawn_foliage`

Places foliage instances across a defined region.  Density, scale range, seed, and area bounds are all configurable.

```json
{
  "mesh": "SM_Tree_Oak",
  "instances_placed": 487,
  "area_m2": 10000.0,
  "density_per_100m2": 50.0,
  "scale_range": [0.9, 1.4],
  "seed": 42
}
```

**Example prompts:**

```
"Populate this forest with 500 trees using SM_Tree_Oak, random scale 0.8–1.4."
"Place dense grass (SM_GrassMeadow) across a 200×200m area."
```

#### `clear_foliage`, `configure_lod`, `generate_collision`

Foliage removal, LOD threshold configuration, and collision generation.  All return before/after state for auditability.

---

### Phase 4 · Landscape & PCG Foundation

#### `list_landscape_layers`

```json
{
  "layers": [
    {"name": "Grass", "layer_info_path": "/Game/Landscape/Layers/LI_Grass",
     "is_weight_blended": true, "average_weight": 0.62},
    {"name": "Dirt", "layer_info_path": "/Game/Landscape/Layers/LI_Dirt",
     "is_weight_blended": true, "average_weight": 0.24}
  ],
  "total": 4
}
```

#### `paint_landscape_layer`, `configure_pcg_graph`

Landscape weight painting and PCG graph parameter updates.  Both tools return affected area / parameter diff for confirmation before committing.

> **Live mode note:** Full landscape weight painting requires either the Python Script Plugin (partial support) or a custom C++ editor plugin for precise control.  The tool is designed to be upgraded with better APIs without breaking the MCP interface.

---

### Phase 5 · Splines, Roads & Structure Composition

#### `list_structure_templates`, `build_structure`

`build_structure` assembles a named preset (`cabin`, `house_small`, `house_large`, `warehouse`, `tower`, `wall_segment`, `archway`) from `templates/structure_templates.json` — spawning every component at its offset/rotation/scale relative to the structure's origin, snapping the origin to ground, and registering the whole footprint as one oriented bounding box in the occupancy grid. `list_structure_templates` returns every preset's footprint and component ids/categories so the AI knows what it can override.

```json
{
  "success": true,
  "structure_type": "cabin",
  "label": "cabin_a1b2c3",
  "origin": {"x": 0.0, "y": 0.0, "z": 0.0},
  "components_spawned": 7,
  "components_failed": 0,
  "grid_registered": true
}
```

Every `default_asset` baked into the template is a placeholder — pass `component_overrides` (JSON: component id or category → real `/Game/...` path) to point components at meshes that exist in your project.

**Example prompts:**

```
"Build a small wooden cabin at (2000, 1500, 0)."
"Place a warehouse, rotated 45 degrees, using my own wall and roof meshes."
```

#### `create_spline_actor`, `add_spline_mesh`, `create_road_segment`

`create_spline_actor` places a spline through an array of control points; `add_spline_mesh` tiles a StaticMesh along every segment. `create_road_segment` is the higher-level wrapper — start point, end point, and width in, a ground-snapped spline with a tiled road mesh (and optional lane-marking mesh) out — and registers the segment as an oriented bounding box in the occupancy grid so structures won't be placed on top of it.

```json
{
  "success": true,
  "label": "Road_9f3a21",
  "length_cm": 2000.0,
  "width_cm": 500.0,
  "grid_registered": true
}
```

**Example prompts:**

```
"Connect these two buildings with a road."
"Lay out a fence along this property boundary using SM_FencePanel."
```

---

### Mock mode behaviour

Every Layer 2 tool returns rich, realistic data when `UE_MOCK_MODE=true`:

| Tool | Mock data source |
|------|-----------------|
| `list_actors` | 10 pre-defined mock actors (lights, meshes, Blueprints, Landscape) |
| `list_levels` | 3 mock levels (1 persistent, 1 loaded sub-level, 1 unloaded sub-level) |
| `list_landscape_layers` | 4 layers: Grass, Dirt, Rock, Snow |
| `spawn_foliage` | Calculates realistic instance count from density × area |
| All write tools | Echo input parameters with before/after diffs |

```bash
# Run in mock mode — no Unreal editor required
UE_MOCK_MODE=true uv run ue5-mcp
```

---

### Editor requirements for live mode

| Tool group | Required UE plugins |
|------------|---------------------|
| All actor tools | Editor Scripting Utilities |
| Level tools | Editor Scripting Utilities |
| Foliage / collision / LOD | Python Script Plugin + FoliageEdit module |
| Landscape / PCG | Python Script Plugin + PCG Plugin (UE 5.2+) |

Enable plugins via **Edit → Plugins** in the editor, then restart.  The Remote Control API plugin must also be enabled (default HTTP port 30010).

---

## Layer 3 · Blueprint Tools — *Done*

> **Let the AI generate and edit game logic — not just content.**

This is where the MCP moves from "assistant" to "co-developer." Claude can create Blueprints, add variables, events, and functions based on plain-language descriptions.

### Tools

**Blueprint generation**

| Tool | Description |
|------|-------------|
| `create_blueprint` | Create a new Blueprint class with a parent class |
| `add_variable` | Add a variable to a Blueprint (type, default value, replication) |
| `add_event` | Add a standard event (BeginPlay, Tick, Overlap, etc.) |
| `add_function` | Create a new function inside a Blueprint |
| `add_custom_event` | Add a named custom event with parameters |
| `compile_blueprint` | Trigger a Blueprint compile and return errors |
| `get_blueprint_info` | Return metadata: parent class, variables, functions, events |
| `find_blueprint_nodes` | Search a Blueprint graph for nodes by type or name |

> **Deep node graph editing** (`add_node`, `connect_pins`, `delete_node`) requires a custom C++ plugin — see Architecture. Graph *inspection* via `find_blueprint_nodes` works in live mode via the Python Script Plugin.

**Example — generate a door Blueprint:**

```
Prompt: "Create a door Blueprint that opens when the player approaches."

MCP executes:
  create_blueprint('BP_Door', 'Actor', '/Game/Props')
  add_variable('/Game/Props/BP_Door', 'IsOpen', 'Boolean')
  add_event('/Game/Props/BP_Door', 'ReceiveActorBeginOverlap')
  add_function('/Game/Props/BP_Door', 'OpenDoor')
  compile_blueprint('/Game/Props/BP_Door')
```

---

## Layer 4 · Debugging Tools — *Done*

> **Give the AI the ability to diagnose and fix real problems.**

Instead of copy-pasting logs into chat, the AI can inspect the editor state directly and form conclusions.

### Tools

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
| `get_shader_complexity` | Enable shader complexity view mode and return scores |
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
| `get_output_log` | Retrieve recent Output Log entries, filterable by category/level |
| `get_message_log` | Retrieve the Message Log (compile errors, load warnings) |
| `clear_output_log` | Clear the Output Log |

**Example — player falling through floor:**

```
Claude: check_actor_collision('SM_Floor_01')
Result: collision_enabled='NoCollision'

Claude: set_actor_property('SM_Floor_01', 'CollisionProfileName', 'BlockAll')
Result: Collision restored. Player no longer falls through.
```

---

## Layer 5 · Testing Tools — *Done*

> **Let the AI run and interpret automated tests.**

Connects the MCP to Unreal's built-in testing infrastructure and headless build pipeline.

### Tools

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
| `start_pie` | Launch Play In Editor (1–4 players) |
| `stop_pie` | Stop the current PIE session |
| `get_pie_state` | Check whether a PIE session is active |
| `send_console_command` | Execute a console command in editor or PIE |

**Headless builds**

| Tool | Description |
|------|-------------|
| `build_project` | Trigger a full project build via UnrealBuildTool |
| `cook_content` | Cook content for a target platform via UAT |
| `run_gauntlet_test` | Execute a Gauntlet automated test via UAT |
| `get_build_log` | Retrieve the output from the last build/cook |

---

## Layer 6 · Safety — *Ongoing*

> **The AI is a powerful junior dev — give it the right permissions, not root access.**

Safety features are woven throughout every layer, not bolted on at the end.

| Feature | Status | Description |
|---------|--------|-------------|
| Mock mode | ✅ Done | Full server runs without a live editor (`UE_MOCK_MODE=true`) |
| Graceful fallback | ✅ Done | Three-tier discovery: live editor → filesystem → mock |
| `dry_run=true` | ✅ Done | `delete_actor` and write tools support dry-run |
| Read-only mode | ✅ Done | `UE_READ_ONLY=true` disables all write tools server-wide |
| Audit log | ✅ Done | Append-only JSONL log at `~/.ue5-mcp/audit.jsonl` |
| Scope limiting | ✅ Done | `UE_SCOPE_PATH=/Game/Sandbox` restricts tools to a folder |
| `confirm=true` | Planned | Destructive tools require explicit confirmation per-call |

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
      │    ├── environment.py  ← Layer 2 · done
      │    ├── blueprints.py   ← Layer 3 · done
      │    ├── debugging.py    ← Layer 4 · done
      │    ├── testing.py      ← Layer 5 · done
      │    ├── materials.py    ← Env System · in development
      │    ├── lighting.py     ← Env System · in development
      │    ├── planner.py      ← Env System · in development
      │    └── validation.py   ← Env System · in development
      │
      ├── resources/      ← read-only context (unreal:// URIs)
      ├── prompts/        ← workflow templates
      │
      └── bridge/         ← transport to Unreal
           ├── client.py          (Remote Control HTTP + Python execution)
           ├── audit.py           (append-only audit log — Layer 6)
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
│   │   ├── client.py                 # HTTP client → Remote Control API + Python execution
│   │   ├── audit.py                  # Append-only audit log (Layer 6 safety)
│   │   ├── asset_registry.py         # 27 asset categories + classification engine
│   │   └── asset_scanner.py          # Filesystem Content/ directory scanner
│   ├── tools/
│   │   ├── editor.py                 # ue_ping, ue_get_editor_info
│   │   ├── assets.py                 # list_project_assets, list_asset_categories
│   │   ├── environment.py            # 19 Layer 2 tools + splines/roads/structures (Session 3 done, scatter in dev)
│   │   ├── blueprints.py             # 8 Layer 3 tools (create, variables, events, compile)
│   │   ├── debugging.py              # 15 Layer 4 tools (collision, perf, logs, validation)
│   │   ├── testing.py                # 12 Layer 5 tools (automation, PIE, headless builds)
│   │   ├── materials.py              # 🔄 material assign, instances, parameters (in dev)
│   │   ├── lighting.py               # 🔄 spawn lights, presets, post-process (in dev)
│   │   ├── planner.py                # 🔄 scene planner, zone state, build plan (in dev)
│   │   └── validation.py             # 🔄 spatial checks, auto-fix, build reports (in dev)
│   ├── resources/
│   │   └── engine.py                 # unreal://connection/status, unreal://config
│   ├── prompts/
│   │   └── workflows.py              # explore_level, prototype_gameplay + build workflows (in dev)
│   └── templates/
│       ├── environment_profiles.json # 🔄 asset palettes per biome (in dev)
│       └── structure_templates.json  # ✅ mesh component lists per structure type (cabin, house, warehouse, tower, wall, archway)
└── tests/
    ├── test_server.py                # Layer 1 registry, scanner, UI endpoints
    ├── test_environment.py           # Layer 2 environment tools (97 tests)
    └── test_structure_composition.py # ✅ splines, roads, and build_structure tools (27 tests)
```

---

## Development

```bash
uv sync --extra dev

# Run tests
uv run python -m pytest tests/ -v

# Debug JSON-RPC with MCP Inspector
npx @modelcontextprotocol/inspector uv run ue5-mcp

# Lint
uv run ruff check src/ tests/
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
| Layer 2 · Environment Tools (actors, foliage, levels, landscape) | ✅ Complete |
| Layer 3 · Blueprint Tools (generate, edit, compile) | ✅ Complete |
| Layer 4 · Debugging Tools (collision, performance, logs, validation) | ✅ Complete |
| Layer 5 · Testing Tools (automation, PIE, headless builds) | ✅ Complete |
| Layer 6 · Safety Layer (read-only, dry-run, audit log, scope limit) | ✅ Mostly done |
| **Environment Building System** (materials, lighting, planning, validation, reference translation) | 🔄 **In Development** |
| C++ bridge plugin (deep Blueprint graph editing) | 🔲 Future |

---

## Environment Building System — *In Development*

> **Build complete, coherent environments from a single natural language prompt.**

```
You:    "Make me a forest environment with a few wooden structures."
You:    "Plan out and create a small city with roads, buildings, and cars."
You:    "Design a FPS bomb site map similar to Ascent on Valorant."
MCP:    → translate reference → plan zones → build terrain → place structures
        → assign materials → configure lighting → run validation → report
```

The goal is a full plan-build-check-fix pipeline. The AI describes *what* it wants; the MCP generates a spatial plan, executes it phase by phase, then self-corrects before declaring the build complete.

### The Three-Layer Build Stack

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer C — Intelligence & Orchestration                         │
│  plan_environment · translate_style_reference                   │
│  apply_environment_template · build_environment_from_scratch    │
│  run_correction_pass · generate_build_report                    │
├─────────────────────────────────────────────────────────────────┤
│  Layer B — Composition & Coherence                              │
│  build_structure · create_road_segment · populate_zone          │
│  scatter_assets · apply_lighting_preset · apply_material_palette│
├─────────────────────────────────────────────────────────────────┤
│  Layer A — Core Authoring Tools  ← primary build target         │
│  assign_material · spawn_light · create_spline_actor            │
│  add_spline_mesh · configure_post_process · build_navmesh       │
└─────────────────────────────────────────────────────────────────┘
              (current 58 tools feed into Layer A)
```

---

### Week 1 — Core Authoring Toolkit

**Session 1 · Material System** (`tools/materials.py`)

The highest-impact single addition. Without material tools every placed object remains white clay.

| Tool | Description |
|------|-------------|
| `assign_material` | Assign a material or instance to an actor's mesh component by slot |
| `create_material_instance` | Create a Material Instance asset from a parent material |
| `set_material_parameters` | Set scalar, vector, and texture parameters on a Material Instance |
| `get_material_slots` | Return all material slot names and current assignments on an actor |
| `apply_material_palette` | Batch-assign materials across a list of actors in one call |

`apply_material_palette` is the key tool — it lets the AI dress an entire scene in one call rather than one actor at a time.

---

**Session 2 · Lighting System** (`tools/lighting.py`)

Lighting is what separates a forest at dawn from harsh noon light. Every environment preset starts here.

| Tool | Description |
|------|-------------|
| `spawn_light` | Spawn a directional, point, spot, rect, or sky light at a world location |
| `configure_directional_light` | Set sun angle, intensity, color, and shadow distance (primary time-of-day control) |
| `configure_sky_atmosphere` | Set Rayleigh/Mie scattering and aerial perspective to control sky color palette |
| `configure_post_process` | Exposure, bloom, color grading (shadows/midtones/highlights), depth of field, vignette |
| `apply_lighting_preset` | Apply a curated preset: `forest_dawn`, `city_night`, `golden_hour`, `overcast`, `foggy_midday` |
| `build_lighting` | Trigger a lightmap build via `EditorLevelLibrary` |

`apply_lighting_preset` is the highest-leverage tool — the AI calls one function and gets coherent lighting without configuring 12 individual parameters.

---

**Session 3 · Splines, Roads & Structure Composition** (extend `tools/environment.py`) — *Done*

The difference between a city and a cluster of buildings is connected roads and assembled structures.

| Tool | Description |
|------|-------------|
| `create_spline_actor` | Place a spline actor with an array of control points |
| `add_spline_mesh` | Tile a mesh asset along a spline (roads, fences, rivers, walls) |
| `create_road_segment` | Higher-level: start + end + width + mesh → spline, tiled road mesh, and optional lane markings |
| `list_structure_templates` | Discover available structure presets, their footprint, and overridable component ids/categories |
| `build_structure` | Assemble a structure from component meshes: `cabin`, `house_small`, `house_large`, `warehouse`, `tower`, `wall_segment`, `archway` |
| `create_zone_boundary` | 🔲 Not yet implemented — place invisible blocking volumes and a named outliner folder for a defined zone |

`build_structure` consumes `templates/structure_templates.json`, which maps each structure type to a list of mesh components and their relative offset/rotation/scale. Every default `default_asset` path in that file is a **placeholder** — pass `component_overrides` (component id or category → real `/Game/...` path, found via `list_project_assets`) to point components at meshes that actually exist in your project. Both `build_structure` and `create_road_segment` register their footprint in the occupancy grid as an oriented bounding box, so later `spawn_actor_safe` / `build_structure` / `create_road_segment` calls won't collide with them.

---

**Session 4 · Smart Asset Scattering & Zone Population**

Fills spaces convincingly rather than placing assets one at a time.

| Tool | Description |
|------|-------------|
| `scatter_assets` | Place any asset list across a zone with density falloff, overlap avoidance, and scale/rotation variance |
| `populate_zone` | Fill a named zone based on environment type (`forest`, `urban`, `desert`, `indoor`) using curated density parameters |
| `clear_zone` | Delete all actors within a named zone or set of bounds |
| `create_asset_cluster` | Place a small thematic group of assets (rocks, street furniture, debris) around an anchor point |

`populate_zone` reads an `environment_profiles.json` config that maps each environment type to curated asset lists and density settings — the knowledge of which assets look good together lives in config, not code.

---

### Week 2 — Environment Intelligence Layer

**Session 5 · The Scene Planner** (`tools/planner.py`)

The most important session. Before this, the AI improvises spatial decisions. After this, it generates a machine-readable plan and executes phase by phase.

| Tool | Description |
|------|-------------|
| `plan_environment` | Convert a natural language description into a structured zone map, asset requirements, lighting recommendation, and ordered build phases |
| `get_build_plan` | Retrieve the current active build plan from server state |
| `update_build_plan` | Mark phases complete, record what was built, add notes |
| `get_environment_summary` | Snapshot of everything currently placed: actor counts by type, covered area, material status, lighting state |

`plan_environment` output schema:

```json
{
  "zones": [
    { "name": "forest_core", "purpose": "dense canopy", "bounds": {...}, "environment_type": "forest", "density": 0.9, "priority": 1 }
  ],
  "asset_requirements": ["SM_Tree_Oak", "SM_Fern", "SM_Log"],
  "lighting_recommendation": { "preset": "forest_dawn", "overrides": {} },
  "build_order": ["terrain", "structures", "scatter_vegetation", "foliage", "lighting", "validation"]
}
```

The rule: **always `plan_environment` first, then execute phase by phase, then validate**. This is the loop that makes complex environments spatially coherent.

---

**Session 6 · Environment Templates & Spatial Grammar**

Templates encode the spatial rules that make an environment *feel* like what it's supposed to be.

| Tool | Description |
|------|-------------|
| `list_environment_templates` | Return all available templates with descriptions and recommended map sizes |
| `apply_environment_template` | Expand a named template into a full zone plan and begin build phases |

Built-in templates: `dense_forest` · `sparse_woodland` · `city_block` · `city_district` · `fps_bombsite` · `fps_mid_area` · `abandoned_industrial` · `coastal_village`

A `fps_bombsite` template encodes: outer approach corridor (~30 m), main site area (~20×25 m with 2+ large cover objects), box room flank, rotate path, and maximum sightline distance. These spatial rules are what distinguish a combat map from a random collection of boxes.

---

**Session 7 · Reference Translation System**

Converts any style reference — a game map, an architectural movement, a movie scene, a real place — into a structured design profile.

| Tool | Description |
|------|-------------|
| `translate_style_reference` | Convert a reference string into a structured style profile: color palette, material keywords, spatial characteristics, lighting profile |
| `search_assets_by_style` | Match a style profile against the asset library to find the best-fitting meshes and materials |

Style profile output schema:

```json
{
  "color_palette": { "dominant": "#8B7355", "accent": "#2E4A1E", "shadow": "#1A1A2E" },
  "material_keywords": ["weathered wood", "stone cobble", "terracotta roof"],
  "spatial_characteristics": { "density": 0.7, "verticality": 0.4, "sightline_profile": "short" },
  "lighting_profile": { "preset": "golden_hour", "overrides": { "sky_tint": "#FFD59E" } },
  "reference_notes": "Compact Mediterranean layout, asymmetric sight lines, mixed-height buildings"
}
```

The output feeds directly into `plan_environment`. The implementation is a structured prompt template — engineered to extract the same schema from any reference regardless of source.

---

**Session 8 · Orchestration Prompts & Build Workflows**

Wire the full pipeline into named workflows the AI follows without step-by-step prompting.

New entries in `prompts/workflows.py`:

| Prompt | Workflow |
|--------|---------|
| `build_environment_from_scratch` | translate reference → plan zones → setup lighting → build terrain → place structures → populate → assign materials → validate → report |
| `build_fps_map` | layout playspace → place cover → check sightlines → material pass → lighting → navmesh |
| `iterate_on_environment` | get summary → identify gaps → targeted additions → re-validate |
| `dress_environment` | material pass + lighting pass on an already-placed scene |

These prompts are the scripts the AI reads to know exactly which tool calls to make and in what order. Without them, it improvises. With them, it follows a proven process every time.

---

### Week 3 — Self-Checking, Coherence & Visual Validation

**Session 9 · Spatial Validation System** (`tools/validation.py`)

How the MCP checks its own work. Catches floating objects, overlapping structures, bare materials, and broken sightlines before the build is declared done.

| Tool | Description |
|------|-------------|
| `check_floating_actors` | Find static mesh actors whose bounding box bottom is above terrain by more than a threshold |
| `check_actor_overlaps` | Find pairs of actors whose bounding boxes intersect (excludes intentional overlaps) |
| `check_zone_coverage` | Measure what percentage of each planned zone has been populated — detects zones that were planned but never filled |
| `check_material_coverage` | Scan all visible static meshes and flag any with a default or missing material |
| `check_sightlines` | For FPS maps: report sightline distances from common player positions, flag angles exceeding `max_sightline_meters` |
| `validate_environment` | Master tool — runs all checks above and returns a structured report of `issues`, `warnings`, and `passed_checks` |

---

**Session 10 · Auto-Fix & Iterative Correction**

Validation without correction is diagnosis. These tools close the loop.

| Tool | Description |
|------|-------------|
| `snap_actors_to_ground` | Trace a ray downward from each actor and move it to the surface hit point |
| `resolve_actor_overlaps` | Move lower-priority actors to the nearest non-overlapping position |
| `fill_empty_zones` | Check zone coverage and call `populate_zone` to fill sparse areas |
| `apply_missing_materials` | Look up each bare actor's type, find the best-match material from the environment profile, and assign it |
| `run_correction_pass` | Run `validate_environment` → auto-apply all fixable issues → re-validate → report what remains |

Every build workflow ends with `run_correction_pass`. The MCP never declares a build complete without it.

---

**Session 11 · Screenshot Capture & Build Report**

The "eyes" of the self-check system — lets the AI see what it has built.

| Tool | Description |
|------|-------------|
| `capture_editor_screenshot` | Capture the current viewport via `AutomationLibrary.take_high_res_screenshot` and return the file path |
| `get_viewport_overview` | Position the editor camera top-down over the scene and capture a full overview screenshot |
| `generate_build_report` | Compile zone coverage stats, actor counts, material coverage %, lighting status, validation results, and viewport screenshots into a markdown report |
| `compare_to_reference` | Score the current environment against a style profile across density, verticality, material palette, and sightline dimensions — return a diff and suggested adjustments |

---

**Session 12 · Integration, Safety & Environment Gallery**

| Addition | Description |
|----------|-------------|
| Three end-to-end test builds | `build_forest_with_structures`, `build_small_city`, `build_fps_bombsite` — full plan-to-report pipelines |
| `undo_last_build_phase` | Read the audit log and reverse all actor spawns from the most recent phase — the safety net when a phase goes wrong |
| `environment_gallery` resource | New `unreal://environments/gallery` resource listing previously built environments with their plans and screenshot paths |
| `tests/test_environment_v2.py` | Full pytest coverage for all new tools |

---

### New Files Added by This System

```
src/ue5_mcp/
├── tools/
│   ├── materials.py          ← Session 1 · material assign/create/parameter tools
│   ├── lighting.py           ← Session 2 · spawn lights, presets, post-process
│   ├── planner.py            ← Session 5 · scene planner, zone definitions, build state
│   └── validation.py         ← Session 9 · spatial checks and auto-fix tools
├── templates/
│   ├── environment_profiles.json   ← asset palettes per biome (forest, urban, etc.)
│   └── structure_templates.json    ← mesh component lists per structure type
└── tests/
    └── test_environment_v2.py      ← coverage for all new tools
```

`environment.py` is extended with spline, road, scatter, and zone population tools. `prompts/workflows.py` is extended with the four new build workflows.

---

### Design Principles

**The plan always comes before the build.** `plan_environment` generates a machine-readable zone map before any actor is spawned. Every workflow prompt enforces this.

**Every build phase is logged.** Each `spawn_actor` call records the plan phase it belongs to in the audit log. This is what enables `undo_last_build_phase`.

**Curated config files are as important as the tools.** `environment_profiles.json` and `structure_templates.json` encode which assets look good together, which densities feel natural, and which lighting settings match each biome. This curation is the difference between "technically built" and "actually looks good."

**Self-check is non-negotiable.** Every workflow prompt ends with `run_correction_pass` and `generate_build_report`. The MCP never considers a build complete without running both.

---

## License

MIT — see [LICENSE](LICENSE).
