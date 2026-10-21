# 3D train tracker

Live 3D view of any two Indian Railways trains on the stretch of route they share: real positions from NTES,
distance between them, overtakes, day/night, and sound (your own horn and track recordings).

Type two 5-digit train numbers and press **Load**. Nothing about any particular train is hard-coded - route, stations
(including non-stopping ones), coach count, top speed and the run to track all come from NTES.

## Run locally
```
python server.py        # then open http://localhost:8765/   (or double-click start_server.bat)
```
Python 3.8+, no packages to install.

## Deploy on Vercel
Import this repo in Vercel - no settings needed. `index.html` + `assets/` are served statically and
`api/status.py` is a Python serverless function (it imports `ntes.py`, see `vercel.json`).

Notes
- NTES has no public API. `ntes.py` uses the same session + CSRF-token flow the NTES website does. It may break if NTES changes its pages,
  and NTES may refuse requests from some hosting IP ranges - if the deployed site shows "no data" but it works locally, that is the likely cause.
- Live positions are NTES's last confirmed location plus extrapolation, not GPS.
- Sounds: `assets/horn.mp3`, `assets/track.mp3` (replace them to change the sounds).
