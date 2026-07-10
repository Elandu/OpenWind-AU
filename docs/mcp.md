# MCP Server

OpenWind-AU includes a Model Context Protocol server for deterministic Australian wind-variable
calculations through `Vsit,b`. It uses the stable v1 Python SDK and supports stdio and Streamable
HTTP transports.

## Install

```bash
python -m pip install -e ".[dev]"
```

The MCP dependency is constrained to `mcp>=1.27,<2` because the official v2 SDK is still a
pre-release. Update that constraint only after testing the v2 migration.

## Configure A Stdio Client

```json
{
  "mcpServers": {
    "openwind-au": {
      "command": "openwind-au-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

When running from a source checkout without an editable install, use the virtual-environment
Python executable and `-m openwind_au.mcp_server` instead.

## Run Streamable HTTP

```bash
openwind-au-mcp --transport streamable-http --host 127.0.0.1 --port 8001
```

Connect an MCP client to `http://127.0.0.1:8001/mcp`. The equivalent environment variables are
`OPENWIND_MCP_TRANSPORT`, `OPENWIND_MCP_HOST`, and `OPENWIND_MCP_PORT`.

## Tools

- `calculate_regional_wind_speed`: Table 3.1(A) regional equation and prescribed rounding.
- `get_direction_multipliers`: Table 3.2(A) multipliers for all eight directions.
- `calculate_terrain_height_multiplier`: Table 4.1 height/category interpolation and A0 rules.
- `calculate_shielding_multiplier`: Table 4.2 interpolation, with `Ms = 1.0` for `h > 25 m`.
- `calculate_topographic_wind_multiplier`: Clause 4.4 calculation with intermediate values.
- `calculate_site_wind_speed`: reviewed-input `Vsit,b` product.
- `calculate_all_wind_variables`: a traceable combined result for one direction.

Each tool returns the standard edition, clause/table reference, inputs, outputs, warnings, and an
engineering-review flag. The server calculates from supplied, reviewed inputs; it does not certify
terrain category, obstruction suitability, topographic survey geometry, jurisdictional variations,
or compliance.

## Verify

```bash
pytest tests/test_mcp_server.py tests/test_standard_lookup_tables.py tests/test_wind_inputs.py
ruff check .
```
