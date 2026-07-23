# MCP Server

OpenWind-AU includes a Model Context Protocol server for deterministic Australian wind-variable
calculations through `Vsit,b`. It uses the stable v1 Python SDK and supports stdio and Streamable
HTTP transports.

## Install

For a wheel artifact built from the exact reviewed commit:

```powershell
python -m pip install .\openwind_au-0.8.0-py3-none-any.whl
openwind-au-mcp --help
```

For a development checkout:

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
`OPENWIND_MCP_TRANSPORT`, `OPENWIND_MCP_HOST`, and `OPENWIND_MCP_PORT`. Environment defaults are
validated before the server starts: transport must be `stdio` or `streamable-http`, host must be
non-empty, and port must be an integer from 1 through 65535. Explicit command-line options take
precedence over their environment equivalents.

DNS-rebinding protection remains enabled for HTTP. A wildcard bind therefore requires each trusted
Host header to be explicit:

```bash
openwind-au-mcp --transport streamable-http --host 0.0.0.0 --port 8001 \
  --allowed-host wind.example
```

Repeat `--allowed-host` for additional names or IP addresses. For browser clients, repeat
`--allowed-origin` for each trusted `http://` or `https://` origin. The environment equivalents are
comma-separated `OPENWIND_MCP_ALLOWED_HOSTS` and `OPENWIND_MCP_ALLOWED_ORIGINS`. Do not expose an
unauthenticated MCP endpoint to an untrusted network; place remote deployments behind appropriate
network access controls and authentication.

On a Windows mapped or UNC network drive, the generated console launcher can inherit a UNC Python
path that prevents native `pywin32` modules from loading. Use the environment's interpreter
directly in that case:

```powershell
.\.venv\Scripts\python.exe -m openwind_au.mcp_server `
  --transport streamable-http --host 127.0.0.1 --port 8001
```

## Tools

- `calculate_regional_wind_speed`: Table 3.1(A) regional equation or configured VR table.
- `calculate_climate_change_multiplier`: Clause 3.4/Table 3.3 `Mc` for a reviewed region.
- `get_direction_multipliers`: Table 3.2(A) multipliers for all eight directions.
- `calculate_terrain_height_multiplier`: Table 4.1 height/category interpolation and A0 rules.
- `calculate_shielding_multiplier`: Table 4.2 interpolation, with `Ms = 1.0` for `h > 25 m`.
- `calculate_topographic_wind_multiplier`: Clause 4.4 calculation with intermediate values.
- `calculate_site_wind_speed`: reviewed-input Clause 2.2
  `VR x Mc x Md x Mz,cat x Ms x Mt` product.
- `calculate_all_wind_variables`: a traceable combined result for one direction.

The combined tool requires a `wind_direction_multiplier_case`. It enforces `Md = 1.0` for the
Clause 3.3 chimney/tank/pole case and for cladding or its immediate supporting structure in B2, C
and D. It accepts `average_roof_height_m` separately from overall `building_height_m` and uses the
average roof height for `Mz,cat`, the 25 m shielding rule, and Clause 4.4. Generic Region `B` is
rejected for `Mc`; callers must identify B1 or B2.

The published tool schemas narrow the region choices to the calculation being performed. Generic A
is available only to standalone regional-speed and climate-change calculations; direction,
terrain-height, topographic, and combined calculations require A0 through A5. Generic B remains
available to standalone regional-speed, terrain-height, and topographic calculations, while
climate-change, direction, and combined calculations require B1 or B2.

Each tool returns the standard edition, clause/table reference, inputs, outputs, warnings, and an
engineering-review flag. The server calculates from supplied, reviewed inputs; it does not certify
terrain category, obstruction suitability, topographic survey geometry, jurisdictional variations,
or compliance.

The initialization handshake reports the OpenWind-AU application version. Tool schemas enumerate
supported wind regions, directions, terrain categories, and topographic feature types, publish
numeric bounds, and define the required result envelope. The MCP boundary rejects booleans and
numeric strings where an engineering number is required instead of silently coercing them.

The MCP server uses the same lookup selection paths as the web API. This includes
`OPENWIND_VR_TABLE_PATH`, `OPENWIND_MD_TABLE_PATH`, `OPENWIND_MZCAT_TABLE_PATH`, and
`OPENWIND_MS_TABLE_PATH`. When `OPENWIND_VR_TABLE_PATH` is unset, both surfaces use the regional
equation and prescribed rounding. A configured VR table may supply an exact reviewed ARI row;
missing rows are not interpolated, and an unchanged packaged row retains the equation path for
non-tabulated `R >= 5` values. The MCP calculation fails closed if no value can be resolved because
it cannot continue `Vsit,b` with a missing VR. Region C/D default values are labelled as regional
maxima because distance-based coastal interpolation is not implemented. Unsupported Australian
wind-region labels are rejected rather than falling through to an ordinary-region calculation.

## Verify

```bash
pytest tests/test_mcp_server.py tests/test_standard_lookup_tables.py tests/test_wind_inputs.py
ruff check .
```
