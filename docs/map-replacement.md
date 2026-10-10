# Map replacement verification — 2026-10-10

- Full Python suite: 118 passed, 12 skipped (Oracle-dependent tests).
- Eight map regressions cover polygon membership, the formerly clipped eastern area, invalid/imputed coordinates, year/barangay/severity filters, counts, boundary edges and API/template integration.
- Headless Edge: desktop 1440 px and mobile 390 px; no uncaught JavaScript errors or mobile horizontal overflow. Verified filters, selectable rankings, crash-point toggle, reset, API failure recovery and empty results.
- Visual inspection corrected opaque-pass heat leakage by rendering the outside mask in the translucent pass at 0.9999 opacity. Resizing refits the entire municipal boundary.
- Sample CSV: 2,795 selected; 2,737 plotted; 58 excluded from spatial display. These counts describe the test CSV, not a fresh Oracle database audit.
- Local boundary and MapLibre assets are bundled with provenance/license. No polygon downloads happen at page load.
- No production dataset edits or deployment/restart performed.

See map-desktop.png, map-mobile.png, and map-cleanup.json in this directory.

## Tile provider and heat style update

OpenStreetMap volunteer raster tiles displayed an access-blocked image. Replaced their direct URL with OpenFreeMap's public vector tile service and its local Liberty style. Browser QA confirmed successful OpenFreeMap resources, correct automatic attribution, no request to `tile.openstreetmap.org`, and working filters on desktop and mobile. The standard basemap retains its colors. The latest map screenshots reflect the continuous heatmap refinement below. OpenFreeMap's public service has no SLA; the boundary and heat remain available without its street tiles.

## Continuous heatmap refinement

The reference calls for a continuous translucent orange-to-red surface. Removed the stacked D3 contour bands and display-site count dampening. Each eligible crash now contributes equally to a MapLibre heatmap with broad overlapping kernels, transparent low-density tails and soft red centers. No discrete levels, fabricated jitter or changes to the basemap. The map page no longer loads D3; the library remains available to the pattern explorer.

Desktop and mobile browser QA passed for filters, points, reset, empty results, API error recovery and OpenFreeMap requests. Visual inspection confirmed continuous fading edges and blended nearby clusters. The latest screenshots show this version.
