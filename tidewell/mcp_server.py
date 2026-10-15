"""Tidewell as an MCP server: plug the same four tools into Claude Desktop (or any MCP client).

This is the pattern Samir Saci uses for his network optimisation agent: the optimiser stays ordinary Python, and an MCP
server hands it to Claude as typed tools with long, explicit descriptions. Here the tools and descriptions are the very
same objects the website uses (tidewell/assistant.py), so both front doors give identical numbers.

Run it yourself (it runs on your machine, your Claude subscription does the talking, nobody else pays):

    pip install -r requirements.txt
    python -m tidewell.mcp_server            # speaks MCP over stdio

Claude Desktop config (Settings > Developer > Edit config), with the path to your clone:

    {"mcpServers": {"tidewell": {"command": "python", "args": ["-m", "tidewell.mcp_server"],
                                 "cwd": "/path/to/supply-chain-optimization"}}}

The server also offers one prompt, "supply_chain_analyst", which loads the same instructions the website uses.
"""
import anyio
from mcp import types
from mcp.server.lowlevel import Server
from . import assistant, store

INSTRUCTIONS = ("Supply chain calculators (safety stock, lot sizing, warehouse network design) for your own data, plus "
                "the Tidewell worked example. Every number comes from code, not estimates. For best results, use the "
                "supply_chain_analyst prompt.")


def build(co=None):
    co = co if co is not None else store.build()[0]
    box = assistant.Toolbox(co)

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=[types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
                                            for t in box.tools])

    async def call_tool(ctx, params):
        try:
            # The solver is blocking work; keep it off the event loop.
            out, _ = await anyio.to_thread.run_sync(box.call, params.name, dict(params.arguments or {}))
            return types.CallToolResult(content=[types.TextContent(type="text", text=assistant.as_text(out))], is_error=False)
        except ValueError as e:
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(e))], is_error=True)
        except Exception:
            return types.CallToolResult(content=[types.TextContent(type="text", text="The calculation could not run with these inputs.")],
                                        is_error=True)

    async def list_prompts(ctx, params):
        return types.ListPromptsResult(prompts=[types.Prompt(name="supply_chain_analyst",
                                                             description="Work as a supply chain analyst: numbers from the tools, ending with what to do next.")])

    async def get_prompt(ctx, params):
        if params.name != "supply_chain_analyst":
            raise ValueError(f"Unknown prompt {params.name}.")
        return types.GetPromptResult(description="Supply chain analyst", messages=[
            types.PromptMessage(role="user", content=types.TextContent(type="text", text=assistant.SYSTEM))])

    return Server("tidewell", version="1.0", instructions=INSTRUCTIONS, on_list_tools=list_tools, on_call_tool=call_tool,
                  on_list_prompts=list_prompts, on_get_prompt=get_prompt), box


async def _serve():
    from mcp.server.stdio import stdio_server
    server, _ = build()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_serve)
