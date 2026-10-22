# 3D train tracker

Live 3D view of any two Indian Railways trains on the stretch of route they share: real positions from NTES,
distance between them, overtakes, day/night, and sound (your own horn and track recordings) - and, optionally,
the **real landscape** (Google Photorealistic 3D Tiles) under the trains.

Type two 5-digit train numbers and press **Load**. Nothing about any particular train is hard-coded - route, stations
(including non-stopping ones), coach count, top speed and the run to track all come from NTES.

## Run locally
```
python server.py        # then open http://localhost:8765/   (or double-click start_server.bat)
```
Python 3.8+, no packages to install.

## Real landscape (optional)
1. Make a free account at [cesium.com](https://cesium.com/ion/) and create an access token.
2. Paste it into **Real landscape** in the side panel and press **Save** (it is stored only in your browser's local storage).
3. Load two trains, tick **Real Google Earth landscape**.

What happens: the server looks up the shared stations in OpenStreetMap by their station code and traces the railway line between them
(`geo.py`, cached in `geo_cache.json`). The trains then follow that real line and the 3D tiles are placed under them, with the ground
height found by ray-casting the tiles. The first time a stretch is used this can take a few minutes because the public Overpass servers are slow and
often busy; if it fails, untick and tick the box to retry (finished pieces are cached).

- Cesium's free Community plan allows 1,000 Google-tile sessions a month and is for non-commercial use. Google's attribution is shown on the map.
- Real-landscape mode needs the local server (OpenStreetMap lookups are too slow for serverless), so it is not available on the Vercel deployment.
- Coverage varies: rural India is often satellite imagery draped on terrain with few real 3D buildings or trees.

## Deploy on Vercel
Import this repo in Vercel - no settings needed. `index.html` + `assets/` are served statically and
`api/status.py` is a Python serverless function (it imports `ntes.py`, see `vercel.json`).

Notes
- NTES has no public API. `ntes.py` uses the same session + CSRF-token flow the NTES website does. It may break if NTES changes its pages,
  and NTES may refuse requests from some hosting IP ranges - if the deployed site shows "no data" but it works locally, that is the likely cause.
- Live positions are NTES's last confirmed location plus extrapolation, not GPS.
- Sounds: `assets/horn.mp3`, `assets/track.mp3` (replace them to change the sounds).
