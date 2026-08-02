# Example Workflow

1. Start the local server:

```bash
openwind-au
```

2. Open the web UI:

```text
http://127.0.0.1:8000
```

3. Enter an Australian street address and select an autocomplete result, or provide coordinates
   through the API. Entering a new address replaces any previously saved dragged map location.

4. Enter the building height in metres. Optionally enter both building dimensions and set the
   front-face orientation as a clockwise-from-North azimuth (`0`, `90`, `180`, and `270` point the
   front North, East, South, and West).

5. On the map, drag the Design building footprint to move it, drag the orientation handle to
   rotate it through the full 360 degrees, or drag a corner handle to change its breadth and depth.
   These edits update the form and invalidate an earlier result until the assessment is rerun.

6. If reviewed source material identifies mixed-terrain transition distances, add ordered terrain
   intervals for each affected direction. Every interval needs a source reference and must cover
   the complete Clause 4.2.3 averaging window. For non-A0 workflow requests, this calculation
   requires an average roof height `h <= 25 m`. A0 profiles may be incomplete because they are
   retained as unweighted evidence for the mandatory terrain-independent value. Aggregate map
   percentages do not generate the intervals.

7. Run the analysis.

8. Review:

- Site coordinates.
- Ground elevation.
- Eight terrain profiles: N, NE, E, SE, S, SW, W, and NW.
- Analysis radius and profile endpoints.
- Detected ridges, hills, escarpments, and valleys.
- Crest RL, base RL, H, Lu, x, and average upwind slope.
- Clause 4.2.3 segment distances, terrain categories, source references, and non-A0 weights (or A0
  evidence-only status) where a mixed profile was supplied.
- Assumptions and limitations.

9. Open the Documents tab to view the concise HTML report or generate the compact PDF in the
   browser PDF viewer.

For complete REST and MCP request examples, see [`docs/api.md`](../docs/api.md) and
[`docs/mcp.md`](../docs/mcp.md).

All outputs are preliminary and require review by a competent engineer.
