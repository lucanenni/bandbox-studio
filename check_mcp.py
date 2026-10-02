"""Exercise stdio MCP; optional live flags call read-only device tools."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "server.py")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            reads = {"bandbox_inspect", "bandbox_read_state", "bandbox_list_presets", "bandbox_read_current_preset"}
            readonly = reads | {"bandbox_prepare_drive_change", "bandbox_effect_catalog",
                                "bandbox_list_controls", "bandbox_read_tool", "bandbox_read_preset"}
            writes = {"bandbox_apply_drive_change", "bandbox_set_tool", "bandbox_control_looper", "bandbox_set_mixer_volume", "bandbox_select_preset",
                      "bandbox_create_preset", "bandbox_save_as", "bandbox_save_user_preset",
                      "bandbox_rename_preset", "bandbox_set_effect_parameter",
                      "bandbox_set_effect_model", "bandbox_set_effect_active"}
            assert names == readonly | writes, names
            assert all(t.annotations.readOnlyHint == (t.name in readonly) for t in tools.tools)
            output = {"server": init.serverInfo.model_dump(), "tools": sorted(names), "results": {}}
            # These catalogs are local files/code. The default check never
            # launches the native Bluetooth helper or reads device state.
            for name, required in (("bandbox_effect_catalog", {"models", "slots"}),
                                   ("bandbox_list_controls", {"readable_controls", "mixer_controls"})):
                result = await session.call_tool(name, {})
                assert not result.isError, result
                data = json.loads(next(c.text for c in result.content if c.type == "text"))
                assert required <= data.keys(), name
                output["results"][name] = {"validated": True}
            if any(a in sys.argv for a in ("--live", "--live-presets", "--live-current")):
                failures = []
                selected = {"bandbox_list_presets"} if "--live-presets" in sys.argv else reads
                if "--live-current" in sys.argv:
                    selected = {"bandbox_read_current_preset"}
                for name in sorted(selected):
                    result = await session.call_tool(name, {})
                    assert not result.isError, result
                    data = json.loads(next(c.text for c in result.content if c.type == "text"))
                    output["results"][name] = data
                    if (data["exit_code"] != 0 or not data["connected"]
                            or (name == "bandbox_read_state" and not data["query_response_verified"])
                            or (name == "bandbox_list_presets" and not data["preset_list_verified"])
                            or (name == "bandbox_read_current_preset" and not data["current_preset_read_verified"])):
                        failures.append(name)
                output["failed_tools"] = failures
            print(json.dumps(output, indent=2))
            if output.get("failed_tools"):
                raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
