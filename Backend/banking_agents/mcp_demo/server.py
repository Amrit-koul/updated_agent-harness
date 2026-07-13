"""Safe deterministic MCP server for the Agent Harness."""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .service import calculate_repayment_plan as _calculate_repayment_plan
from .service import get_customer_summary as _get_customer_summary
from .service import get_policy_metadata as _get_policy_metadata


mcp = FastMCP("agent-harness-banking")


@mcp.tool()
async def get_policy_metadata() -> str:
    """Return metadata from the backend policy repository."""
    return json.dumps(_get_policy_metadata(), sort_keys=True)


@mcp.tool()
async def calculate_repayment_plan(principal: float, annual_rate_pct: float, months: int) -> str:
    """Calculate a deterministic amortized repayment plan."""
    return json.dumps(_calculate_repayment_plan(principal, annual_rate_pct, months), sort_keys=True)


@mcp.tool()
async def get_customer_summary(account_id: str) -> str:
    """Return a governed Collections customer account summary."""
    return json.dumps(_get_customer_summary(account_id), sort_keys=True)


if __name__ == "__main__":
    mcp.run(transport="stdio")
