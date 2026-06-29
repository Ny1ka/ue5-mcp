"""Testing tools — Layer 5 of the Unreal MCP platform.

This module connects the AI to Unreal's built-in testing infrastructure:
  • Automation tests (UE's built-in functional / unit test system)
  • Play In Editor (PIE) session control
  • Console commands during runtime
  • Build and cook operations via UnrealBuildTool / UAT

Tools are organised into three groups:

  Group 1 · Functional Tests (Automation Framework)
    list_automation_tests, run_automation_test,
    get_test_results, run_all_tests

  Group 2 · Play In Editor
    start_pie, stop_pie, get_pie_state, send_console_command

  Group 3 · Headless Builds
    build_project, cook_content, run_gauntlet_test, get_build_log

All tools:
  • Work in mock mode (UE_MOCK_MODE=true)
  • Return structured JSON via client.format_json()
  • Handle UEConnectionError gracefully
  • Audit destructive/write operations via bridge/audit.py

Note: build_project, cook_content, and run_gauntlet_test invoke
UnrealBuildTool / UAT on the host machine. They require that the UE
Editor is installed (not just the binary) and that the project's
.uproject file path is set in UE_PROJECT_PATH.
"""

from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

from ue5_mcp.bridge import audit
from ue5_mcp.bridge.client import UEClient, UEConnectionError


def register_testing_tools(mcp: FastMCP, client: UEClient) -> None:
    """Register all Layer 5 testing tools on the MCP server."""

    settings = client.settings

    # ==================================================================
    # GROUP 1 · FUNCTIONAL TESTS (AUTOMATION FRAMEWORK)
    # ==================================================================

    @mcp.tool()
    async def list_automation_tests(
        filter_pattern: Annotated[
            str,
            "Optional substring to filter test names. "
            "Example: 'Gameplay' returns only tests with 'Gameplay' in their name. "
            "Leave empty to list all registered tests.",
        ] = "",
    ) -> str:
        """List all automation tests registered in the project.

        UE's Automation Framework discovers tests by scanning the project and
        engine for classes that inherit from FAutomationTestBase or the
        Blueprint-friendly AFunctionalTest.

        Each test entry contains:
          • name — full test identifier used by run_automation_test
          • display_name — human-readable label
          • type — Functional, Unit, or Performance
          • last_status — result from the most recent run (if any)
          • last_duration_ms — time the last run took

        Use filter_pattern to narrow the list to a specific subsystem
        (e.g. 'AI', 'UI', 'Physics') before running tests.
        """
        try:
            result = await client.list_automation_tests(filter_pattern)
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock test list. Connect a live editor for real registered tests. "
                    "Enable the automation system via Window → Test Automation."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("list_automation_tests", str(exc)))

    @mcp.tool()
    async def run_automation_test(
        test_name: Annotated[
            str,
            "Full automation test name, e.g. 'Project.Gameplay.PlayerMovement'. "
            "Use list_automation_tests to discover valid names.",
        ],
        timeout_seconds: Annotated[
            int,
            "Maximum time to wait for the test to complete (seconds). "
            "Default 60. Functional tests may take longer — increase for complex tests.",
        ] = 60,
    ) -> str:
        """Run a specific automation test by its full name.

        Dispatches the test via the Automation Framework and waits for the
        result up to timeout_seconds.  In live mode the test runs inside the
        editor session; no PIE is required for unit/functional tests.

        Returns:
          • status — 'pass', 'fail', or 'timeout'
          • duration_ms — time the test took to run
          • errors — list of failure messages if status='fail'
          • logs — test-specific log output

        After running, call get_test_results to retrieve the full result set
        if you ran multiple tests in sequence.
        """
        if not test_name.strip():
            return client.format_json(
                _error("run_automation_test", "test_name must not be empty.")
            )
        if timeout_seconds < 1 or timeout_seconds > 3600:
            return client.format_json(
                _error("run_automation_test",
                       "timeout_seconds must be between 1 and 3600.")
            )

        try:
            result = await client.run_automation_test(test_name, timeout_seconds)
            payload: dict[str, Any] = {
                **result,
                "dispatched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "run_automation_test",
                               {"test_name": test_name,
                                "timeout_seconds": timeout_seconds}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("run_automation_test", str(exc)))

    @mcp.tool()
    async def get_test_results(
    ) -> str:
        """Return pass/fail results from the most recent automation test run.

        Call this after run_automation_test or run_all_tests to retrieve the
        complete result set.  Results persist until the next test run or until
        the editor session is restarted.

        Returns:
          • tests — list of test results with status and errors
          • summary — aggregated pass/fail/skip counts
          • run_at — timestamp of the last test run
        """
        try:
            result = await client.get_test_results()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if result.get("mock"):
                payload["note"] = (
                    "Mock test results. Run tests in a live editor session "
                    "for real pass/fail data."
                )
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_test_results", str(exc)))

    @mcp.tool()
    async def run_all_tests(
        filter_pattern: Annotated[
            str,
            "Optional filter — only run tests whose name contains this substring. "
            "Example: 'Project.' runs only project tests, not engine tests. "
            "Leave empty to run every registered test.",
        ] = "",
    ) -> str:
        """Run the full automation test suite and return a summary.

        Dispatches all registered tests (or a filtered subset) and waits for
        completion.  Returns a summary with pass/fail counts and the full test
        results list.

        Warning: Running all tests can take several minutes on large projects.
        Use filter_pattern to run only the relevant subset.

        After the run completes, use get_test_results to retrieve per-test
        detail including failure messages.
        """
        try:
            result = await client.run_all_tests(filter_pattern)
            payload: dict[str, Any] = {
                **result,
                "dispatched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "run_all_tests",
                               {"filter_pattern": filter_pattern or None}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("run_all_tests", str(exc)))

    # ==================================================================
    # GROUP 2 · PLAY IN EDITOR (PIE)
    # ==================================================================

    @mcp.tool()
    async def start_pie(
        num_players: Annotated[
            int,
            "Number of player controllers to spawn. Range 1–4. Default 1. "
            "Use 2+ to test multiplayer scenarios.",
        ] = 1,
        spawn_at_player_start: Annotated[
            bool,
            "If true, spawn players at the PlayerStart actor. "
            "If false, spawn at the current editor camera location. Default true.",
        ] = True,
    ) -> str:
        """Launch a Play In Editor (PIE) session.

        PIE starts gameplay inside the editor without building or launching a
        separate executable.  It is the fastest way to test gameplay mechanics,
        AI behaviour, and Blueprint logic.

        Requires: A level must be open.  The editor must not already be in PIE.

        After starting PIE, use send_console_command to execute runtime console
        commands (e.g. 'stat fps', 'ai.DebugDraw 1') or stop_pie to end
        the session.
        """
        if num_players < 1 or num_players > 4:
            return client.format_json(
                _error("start_pie", "num_players must be between 1 and 4.")
            )

        try:
            result = await client.start_pie(num_players, spawn_at_player_start)
            payload: dict[str, Any] = {
                **result,
                "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "start_pie",
                               {"num_players": num_players,
                                "spawn_at_player_start": spawn_at_player_start}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("start_pie", str(exc)))

    @mcp.tool()
    async def stop_pie(
    ) -> str:
        """Stop the current Play In Editor (PIE) session.

        Returns the editor to normal edit mode.  Any unsaved level changes
        made during PIE are discarded — PIE works on a separate transient
        copy of the world.

        If no PIE session is active, this tool returns successfully with
        pie_stopped=false.
        """
        try:
            result = await client.stop_pie()
            payload: dict[str, Any] = {
                **result,
                "stopped_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "stop_pie", {}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("stop_pie", str(exc)))

    @mcp.tool()
    async def get_pie_state(
    ) -> str:
        """Check whether a PIE session is currently active.

        Returns:
          • is_playing — whether PIE is currently running
          • mode — 'Editor', 'PIE', or 'Simulate'
          • num_players — number of player controllers in the session

        Use this before calling start_pie to avoid launching a duplicate session,
        or before using level-editing tools that require the editor to NOT be in PIE.
        """
        try:
            result = await client.get_pie_state()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_pie_state", str(exc)))

    @mcp.tool()
    async def send_console_command(
        command: Annotated[
            str,
            "Console command to execute. Examples:\n"
            "  'stat fps'              — Show frames per second\n"
            "  'stat unit'             — Show CPU/GPU frame time\n"
            "  'show Collision'        — Visualise collision geometry\n"
            "  'show Collision 0'      — Hide collision geometry\n"
            "  'ai.DebugDraw 1'        — Enable AI debug drawing\n"
            "  'r.ScreenPercentage 75' — Render at 75% resolution\n"
            "  't.MaxFPS 30'           — Cap frame rate at 30 FPS\n"
            "  'pause'                 — Pause gameplay (toggle)\n"
            "  'quit'                  — Exit PIE session",
        ],
    ) -> str:
        """Execute a console command in the editor or active PIE session.

        Console commands are the primary way to inspect and control runtime
        behaviour in UE.  They work in both editor and PIE modes.

        In PIE mode, commands affect the running gameplay world directly.
        In editor mode, commands affect the editor viewport and session.

        Results are typically visible in the Output Log or viewport — use
        get_output_log after executing to capture any output.

        Note: Some commands (e.g. 'stat fps') output to the screen overlay,
        not the log — check the editor viewport after executing.
        """
        if not command.strip():
            return client.format_json(
                _error("send_console_command", "command must not be empty.")
            )

        try:
            result = await client.send_console_command(command)
            payload: dict[str, Any] = {
                **result,
                "executed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            await audit.record(settings, "send_console_command", {"command": command}, result)
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("send_console_command", str(exc)))

    # ==================================================================
    # GROUP 3 · HEADLESS BUILDS
    # ==================================================================

    @mcp.tool()
    async def build_project(
        configuration: Annotated[
            str,
            "Build configuration. Options:\n"
            "  'Development' — Standard developer build (default)\n"
            "  'DebugGame'   — Debug symbols, slower but debuggable\n"
            "  'Shipping'    — Optimised release build, no editor code\n"
            "  'Test'        — Like Shipping but with some testing hooks",
        ] = "Development",
        platform: Annotated[
            str,
            "Target platform. Options: 'Win64', 'Mac', 'Linux', 'Android', 'iOS'. "
            "Default 'Win64'. Must match the current host OS for native builds.",
        ] = "Win64",
    ) -> str:
        """Trigger a full project build via UnrealBuildTool.

        This compiles the project's C++ code (if any) and links the game module.
        Blueprint-only projects do not need to be built — they compile inside
        the editor.

        Requires:
          • UE_PROJECT_PATH set to the .uproject file
          • The UE installation includes the full source / build tools
          • A C++ project (Blueprint-only projects skip C++ compilation)

        The build runs in a subprocess.  While the build is running, the
        tool blocks (up to 30 minutes for a full build).  Monitor progress
        with get_build_log after the tool returns.
        """
        valid_configurations = {"Development", "DebugGame", "Shipping", "Test"}
        if configuration not in valid_configurations:
            return client.format_json(
                _error(
                    "build_project",
                    f"configuration must be one of: {', '.join(sorted(valid_configurations))}.",
                )
            )

        valid_platforms = {"Win64", "Mac", "Linux", "Android", "iOS"}
        if platform not in valid_platforms:
            return client.format_json(
                _error(
                    "build_project",
                    f"platform must be one of: {', '.join(sorted(valid_platforms))}.",
                )
            )

        if settings.ue_mock_mode:
            return client.format_json({
                "mock": True,
                "configuration": configuration,
                "platform": platform,
                "build_result": "Succeeded",
                "duration_seconds": 12.3,
                "exit_code": 0,
                "success": True,
                "note": "Mock build — no actual compilation performed.",
            })

        project_path = settings.ue_project_path
        if not project_path:
            return client.format_json(
                _error(
                    "build_project",
                    "UE_PROJECT_PATH is not set. Set it to the .uproject file path.",
                )
            )

        result = await _run_ubt(project_path, platform, configuration)
        await audit.record(settings, "build_project",
                           {"configuration": configuration, "platform": platform}, result)
        return client.format_json(result)

    @mcp.tool()
    async def cook_content(
        platform: Annotated[
            str,
            "Target cook platform. Options: 'Win64', 'Mac', 'Linux', 'Android', 'iOS'. "
            "Default 'Win64'.",
        ] = "Win64",
        release_version: Annotated[
            str,
            "Release version string for the cooked build, e.g. '1.0.0'. "
            "Used for packaging and patch creation. Default '1.0'.",
        ] = "1.0",
    ) -> str:
        """Cook project content for a target platform.

        Content cooking converts all assets (textures, meshes, Blueprints, audio)
        from their editor format into the optimised format for the target platform.
        Cooking is required before packaging a distribution build.

        Requires:
          • UE_PROJECT_PATH set to the .uproject file
          • Sufficient disk space (cooked output is in Saved/Cooked/)

        Cook time depends on project size — small projects take minutes,
        large ones can take hours.  The output log is written to
        Saved/Logs/Cook-<Platform>-<Timestamp>.log.
        """
        valid_platforms = {"Win64", "Mac", "Linux", "Android", "iOS"}
        if platform not in valid_platforms:
            return client.format_json(
                _error(
                    "cook_content",
                    f"platform must be one of: {', '.join(sorted(valid_platforms))}.",
                )
            )

        if settings.ue_mock_mode:
            return client.format_json({
                "mock": True,
                "platform": platform,
                "release_version": release_version,
                "cook_result": "Succeeded",
                "assets_cooked": 847,
                "duration_seconds": 42.1,
                "output_dir": "Saved/Cooked/Win64/MyGame",
                "exit_code": 0,
                "success": True,
                "note": "Mock cook — no content actually processed.",
            })

        project_path = settings.ue_project_path
        if not project_path:
            return client.format_json(
                _error("cook_content", "UE_PROJECT_PATH is not set.")
            )

        result = await _run_uat_cook(project_path, platform, release_version)
        await audit.record(settings, "cook_content",
                           {"platform": platform, "release_version": release_version}, result)
        return client.format_json(result)

    @mcp.tool()
    async def run_gauntlet_test(
        test_name: Annotated[
            str,
            "Name of the Gauntlet test to run, e.g. 'Game.Flow.Base'. "
            "Use list_automation_tests to find available test names.",
        ],
        platform: Annotated[
            str,
            "Platform to run the Gauntlet test on. Default 'Win64'.",
        ] = "Win64",
    ) -> str:
        """Execute a Gauntlet automated test via the UnrealEditor command line.

        Gauntlet is UE's higher-level test automation framework that runs
        against packaged builds or Editor sessions.  It is used for integration
        tests, performance benchmarks, and device farm testing.

        Requires:
          • UE_PROJECT_PATH set to the .uproject file
          • A packaged or development build available for the target platform
          • Gauntlet scripts in the Build/Scripts directory

        Note: Gauntlet tests are typically run in CI/CD pipelines.  For
        in-editor functional tests, prefer run_automation_test instead.
        """
        if not test_name.strip():
            return client.format_json(
                _error("run_gauntlet_test", "test_name must not be empty.")
            )

        if settings.ue_mock_mode:
            return client.format_json({
                "mock": True,
                "test_name": test_name,
                "platform": platform,
                "status": "pass",
                "duration_seconds": 124.5,
                "success": True,
                "note": "Mock Gauntlet run — no actual test executed.",
            })

        project_path = settings.ue_project_path
        if not project_path:
            return client.format_json(
                _error("run_gauntlet_test", "UE_PROJECT_PATH is not set.")
            )

        result = await _run_uat_gauntlet(project_path, test_name, platform)
        await audit.record(settings, "run_gauntlet_test",
                           {"test_name": test_name, "platform": platform}, result)
        return client.format_json(result)

    @mcp.tool()
    async def get_build_log(
    ) -> str:
        """Retrieve the output from the last project build or cook operation.

        Returns the last 100 lines of the most recent UBT or UAT log file
        from the Saved/Logs/ directory.  Includes error and warning counts.

        Use this after build_project or cook_content to diagnose failures
        without reading the full log file manually.

        Returns:
          • log_path — absolute path to the log file
          • lines — last N lines from the log
          • error_count — number of 'error:' lines in the full log
          • warning_count — number of 'warning:' lines in the full log
          • build_result — 'Succeeded' or 'Failed'
        """
        try:
            result = await client.get_build_log()
            payload: dict[str, Any] = {
                **result,
                "queried_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            return client.format_json(payload)
        except UEConnectionError as exc:
            return client.format_json(_error("get_build_log", str(exc)))


# ---------------------------------------------------------------------------
# Headless build helpers
# ---------------------------------------------------------------------------


async def _run_ubt(
    project_path: str,
    platform: str,
    configuration: str,
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run UnrealBuildTool in a subprocess and return the result."""
    uproject = Path(project_path)
    if not uproject.exists():
        return {
            "error": f"Project file not found: {project_path}",
            "success": False,
        }

    # Detect UE installation directory from the project association file.
    ue_root = _detect_ue_root(uproject)
    if not ue_root:
        return {
            "error": (
                "Could not detect UE installation directory. "
                "Ensure the project is associated with a UE installation."
            ),
            "success": False,
        }

    ubt_path = _find_ubt(ue_root, platform)
    if not ubt_path:
        return {
            "error": f"UnrealBuildTool not found under {ue_root}.",
            "success": False,
        }

    project_name = uproject.stem
    cmd = [
        str(ubt_path),
        f"{project_name}Editor",
        platform,
        configuration,
        str(uproject),
        "-NoHotReload",
    ]

    return await _run_subprocess(cmd, timeout, "build_project")


async def _run_uat_cook(
    project_path: str,
    platform: str,
    release_version: str,
    timeout: int = 3600,
) -> dict[str, Any]:
    """Run UAT cook command in a subprocess."""
    uproject = Path(project_path)
    if not uproject.exists():
        return {"error": f"Project file not found: {project_path}", "success": False}

    ue_root = _detect_ue_root(uproject)
    if not ue_root:
        return {"error": "Could not detect UE installation directory.", "success": False}

    uat_path = Path(ue_root) / "Engine" / "Build" / "BatchFiles" / "RunUAT.sh"
    if not uat_path.exists():
        uat_path = Path(ue_root) / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    if not uat_path.exists():
        return {"error": f"RunUAT not found under {ue_root}.", "success": False}

    cmd = [
        str(uat_path),
        "BuildCookRun",
        f"-project={project_path}",
        f"-platform={platform}",
        "-cook",
        "-stage",
        "-pak",
        "-clientconfig=Development",
        "-serverconfig=Development",
        f"-CreateReleaseVersion={release_version}",
    ]

    return await _run_subprocess(cmd, timeout, "cook_content")


async def _run_uat_gauntlet(
    project_path: str,
    test_name: str,
    platform: str,
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run a Gauntlet test via UAT in a subprocess."""
    uproject = Path(project_path)
    if not uproject.exists():
        return {"error": f"Project file not found: {project_path}", "success": False}

    ue_root = _detect_ue_root(uproject)
    if not ue_root:
        return {"error": "Could not detect UE installation directory.", "success": False}

    uat_path = Path(ue_root) / "Engine" / "Build" / "BatchFiles" / "RunUAT.sh"
    if not uat_path.exists():
        uat_path = Path(ue_root) / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    if not uat_path.exists():
        return {"error": f"RunUAT not found under {ue_root}.", "success": False}

    cmd = [
        str(uat_path),
        "RunUnreal",
        f"-project={project_path}",
        f"-platform={platform}",
        f"-test={test_name}",
    ]

    return await _run_subprocess(cmd, timeout, "run_gauntlet_test")


async def _run_subprocess(
    cmd: list[str],
    timeout: int,
    operation: str,
) -> dict[str, Any]:
    """Execute a subprocess asynchronously and return result."""
    start = datetime.datetime.now(datetime.timezone.utc)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "operation": operation,
                "success": False,
                "error": f"Operation timed out after {timeout} seconds.",
                "command": cmd[0],
            }

        elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
        output_lines = stdout.decode(errors="replace").splitlines()

        # Count errors and warnings in the output.
        error_count = sum(1 for ln in output_lines if "error:" in ln.lower())
        warning_count = sum(1 for ln in output_lines if "warning:" in ln.lower())
        build_result = "Succeeded" if proc.returncode == 0 else "Failed"

        return {
            "operation": operation,
            "command": str(cmd[0]),
            "exit_code": proc.returncode,
            "build_result": build_result,
            "duration_seconds": round(elapsed, 1),
            "error_count": error_count,
            "warning_count": warning_count,
            "lines": output_lines[-100:],
            "success": proc.returncode == 0,
        }
    except FileNotFoundError:
        return {
            "operation": operation,
            "success": False,
            "error": f"Executable not found: {cmd[0]}",
        }
    except OSError as exc:
        return {
            "operation": operation,
            "success": False,
            "error": str(exc),
        }


def _detect_ue_root(uproject: Path) -> str | None:
    """Try to detect the UE installation root from the .uproject association."""
    # Try the ENGINE_ASSOCIATION key inside the .uproject JSON file.
    try:
        import json
        data = json.loads(uproject.read_text())
        engine_assoc = data.get("EngineAssociation", "")
        if engine_assoc:
            # On macOS, UE is at /Users/Shared/Epic Games/UE_5.x
            for search_root in [
                Path("/Users/Shared/Epic Games"),
                Path("/home/epic"),
                Path("C:/Program Files/Epic Games"),
            ]:
                candidate = search_root / f"UE_{engine_assoc}"
                if candidate.exists():
                    return str(candidate)
    except Exception:
        pass

    # Fall back to environment variable.
    env_root = os.environ.get("UE_ROOT") or os.environ.get("UNREAL_ENGINE_ROOT")
    if env_root and Path(env_root).exists():
        return env_root

    return None


def _find_ubt(ue_root: str, platform: str) -> Path | None:
    """Locate the UnrealBuildTool executable."""
    ubt_dir = Path(ue_root) / "Engine" / "Binaries" / "DotNET" / "UnrealBuildTool"
    candidates = [
        ubt_dir / "UnrealBuildTool",
        ubt_dir / "UnrealBuildTool.exe",
        Path(ue_root) / "Engine" / "Build" / "BatchFiles" / "Build.sh",
        Path(ue_root) / "Engine" / "Build" / "BatchFiles" / "Build.bat",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


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
