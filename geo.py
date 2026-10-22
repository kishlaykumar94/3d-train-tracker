"""Real-world geometry for a route: station coordinates and the railway line between them, from OpenStreetMap.

NTES gives distances but no coordinates, so for the 'real landscape' view we look the stations up in OSM by their
station code (OSM tags Indian stations with ref=<code>) and trace the track between consecutive stations through OSM's
railway=rail ways. Public Overpass servers are slow and often busy, so everything is fetched in the background, retried
across mirrors, and cached on disk - the first time a stretch is used it can take a few minutes.
"""
import json, math, os, re, subprocess, threading, time, heapq, hashlib
import railnet

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, "geo_cache.json")
MIRRORS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter",
           "https://overpass-api.de/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
UA = "3d-train-tracker/1.0 (personal project)"
LOCK = threading.Lock()
JOBS = {}            # route key -> {"state": "pending"|"done"|"error", "msg": str, "result": dict}
_cache = None


def cache():
    global _cache
    if _cache is None:
        try:
            _cache = json.load(open(CACHE_FILE, encoding="utf-8"))
        except Exception:
            _cache = {}
        _cache.setdefault("stations", {})
        _cache.setdefault("tracks", {})
    return _cache


def save():
    with LOCK:
        tmp = CACHE_FILE + ".tmp"
        json.dump(cache(), open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, CACHE_FILE)


def overpass(q, tries=6, timeout=75):
    """Run an Overpass query, rotating through mirrors with back-off. Returns parsed JSON or None."""
    for i in range(tries):
        base = MIRRORS[i % len(MIRRORS)]
        try:
            r = subprocess.run(["curl", "-s", "--max-time", str(timeout), "-A", UA, "--data-urlencode", "data=" + q, base],
                               capture_output=True)
            o = r.stdout.decode("utf-8", "ignore")
            if o.lstrip().startswith("{"):
                d = json.loads(o)
                rem = str(d.get("remark", "")).lower()
                if "error" in rem or "timed out" in rem or "out of memory" in rem:
                    raise RuntimeError(rem)
                return d
        except Exception:
            pass
        time.sleep(min(20, 2 + 3 * i))
    return None


def hav(a, b):
    R = 6371008.8
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


_local = None


def local_stations():
    """code -> [lat, lon] from data/stations.json (DataMeet's list of Indian Railways stations), if present."""
    global _local
    if _local is None:
        _local = {}
        try:
            for f in json.load(open(os.path.join(HERE, "data", "stations.json"), encoding="utf-8"))["features"]:
                g, p = f.get("geometry"), f.get("properties", {})
                if g and p.get("code"):
                    _local[p["code"]] = [g["coordinates"][1], g["coordinates"][0]]
        except Exception:
            pass
    return _local


def station_coords(codes):
    """Station lat/lon by code from OpenStreetMap (ref tag). Small queries run in parallel across the Overpass mirrors,
    and whatever is found is used - a few missing stations don't stop the route."""
    c = cache()["stations"]
    loc = local_stations()
    for x in codes:                                   # local station list first: instant, offline
        if x not in c and x in loc:
            c[x] = loc[x]
    need = [x for x in codes if x not in c]
    chunks = [need[i:i + 10] for i in range(0, len(need), 10)]

    def one(chunk):
        rx = "^(" + "|".join(re.escape(x) for x in chunk) + ")$"
        d = overpass(f'[out:json][timeout:40];(nwr["railway"~"^(station|halt)$"]["ref"~"{rx}"](6.0,68.0,37.5,98.0););out center tags;', tries=2, timeout=12)
        if d is None:
            return
        for e in d["elements"]:
            ref = e.get("tags", {}).get("ref")
            ctr = e if "lat" in e else e.get("center")
            if ref in chunk and ctr and ref not in c:
                c[ref] = [ctr["lat"], ctr["lon"]]

    ths = [threading.Thread(target=one, args=(ch,)) for ch in chunks]
    for i in range(0, len(ths), 4):                 # at most 4 queries in flight at once
        [t.start() for t in ths[i:i + 4]]
        [t.join() for t in ths[i:i + 4]]
    if need:
        save()
    return {x: c[x] for x in codes if x in c}


def track_between(pts):
    """pts: list of (lat, lon) in order. Returns a polyline following OSM railway ways, or a straight line on failure."""
    key = hashlib.md5(json.dumps([[round(p[0], 4), round(p[1], 4)] for p in pts]).encode()).hexdigest()
    tc = cache()["tracks"]
    if key in tc:
        return tc[key]
    if railnet.available():                              # local copy of India's railways: instant, no network
        pad = 0.06
        la, lo = [p[0] for p in pts], [p[1] for p in pts]
        ways = railnet.ways(min(la) - pad, min(lo) - pad, max(la) + pad, max(lo) + pad)
    else:                                                # fall back to the public Overpass servers (slow, often busy)
        around = ",".join(f"{p[0]:.5f},{p[1]:.5f}" for p in pts)
        d = overpass(f'[out:json][timeout:120];way["railway"="rail"]["service"!~"yard|siding|spur|crossover"](around:700,{around});out geom;')
        if d is None:
            return None
        ways = [[(g["lat"], g["lon"]) for g in w["geometry"]] for w in d["elements"] if w.get("type") == "way" and "geometry" in w]
    # graph over the line vertices; vertices at the same coordinate are the same node (that is how OSM lines join)
    adj, pos = {}, {}
    for line in ways:
        prev = None
        for la_, lo_ in line:
            nid = (round(la_ * 1e6), round(lo_ * 1e6))
            pos[nid] = (la_, lo_)
            if prev is not None and prev != nid:
                L = hav(pos[prev], pos[nid])
                adj.setdefault(prev, []).append((nid, L))
                adj.setdefault(nid, []).append((prev, L))
            prev = nid
    if not adj:
        return None
    ids = list(pos)

    def nearest(p):
        best, bd = None, 1e18
        for nid in ids:
            q = pos[nid]
            dd = (q[0] - p[0]) ** 2 + ((q[1] - p[1]) * math.cos(math.radians(p[0]))) ** 2
            if dd < bd:
                best, bd = nid, dd
        return best, math.sqrt(bd) * 111320

    def dijkstra(src, dst):
        dist, prev, h = {src: 0.0}, {}, [(0.0, src)]
        while h:
            dd, u = heapq.heappop(h)
            if u == dst:
                break
            if dd > dist.get(u, 1e18):
                continue
            for v, L in adj.get(u, ()):
                nd = dd + L
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(h, (nd, v))
        if dst not in dist:
            return None
        path, u = [dst], dst
        while u != src:
            u = prev[u]
            path.append(u)
        return path[::-1]

    snapped = [nearest(p) for p in pts]
    out = []
    for i in range(len(pts) - 1):
        (a, da), (b, db) = snapped[i], snapped[i + 1]
        seg = dijkstra(a, b) if (da < 800 and db < 800) else None
        straight = hav(pts[i], pts[i + 1])
        line = [list(pos[n]) for n in seg] if seg else None
        if line:                                         # reject detours: the traced line must be about as long as the gap
            L = sum(hav(line[k], line[k + 1]) for k in range(len(line) - 1))
            if L > straight * 1.6 + 500:
                line = None
        if not line:
            line = [list(pts[i]), list(pts[i + 1])]
        out.extend(line if not out else line[1:])
    # drop near-duplicate points
    slim = [out[0]]
    for p in out[1:]:
        if hav(slim[-1], p) > 1.0:
            slim.append(p)
    tc[key] = slim
    save()
    return slim


def build_route(stations):
    """stations: [{code, km}, ...] ordered by km. Returns {stations:[{code,km,lat,lon,s}], poly:[[lat,lon,s],...], missing:[codes]}"""
    coords = station_coords([s["code"] for s in stations])
    have = [s for s in stations if s["code"] in coords]
    missing = [s["code"] for s in stations if s["code"] not in coords]
    if len(have) < 2:
        raise RuntimeError("could not find station coordinates in OpenStreetMap (servers busy?) - try again shortly")
    # trace the line in windows of ~10 stations so each Overpass query stays small
    poly, WIN = [], 10
    for i in range(0, len(have) - 1, WIN - 1):
        win = have[i:i + WIN]
        if len(win) < 2:
            break
        pts = [tuple(coords[s["code"]]) for s in win]
        line = None
        for _ in range(2):
            line = track_between(pts)
            if line:
                break
        if not line:
            raise RuntimeError("OpenStreetMap's public servers are busy or slow right now - tracing the track failed. Untick and tick the box to try again in a few minutes (finished stretches are cached).")
        poly.extend(line if not poly else line[1:])
    # cumulative distance along the polyline, and each station's position on it
    s = [0.0]
    for a, b in zip(poly, poly[1:]):
        s.append(s[-1] + hav(a, b))
    def snap(p):
        best, bd = 0, 1e18
        for i, q in enumerate(poly):
            dd = hav(p, q)
            if dd < bd:
                best, bd = i, dd
        return best
    out_st, last = [], 0
    for st in have:
        p = coords[st["code"]]
        i = min(range(last, len(poly)), key=lambda k: hav(p, poly[k])) if last < len(poly) else len(poly) - 1
        last = i
        out_st.append({"code": st["code"], "km": st["km"], "lat": p[0], "lon": p[1], "s": round(s[i], 1)})
    return {"stations": out_st, "poly": [[round(p[0], 6), round(p[1], 6), round(d, 1)] for p, d in zip(poly, s)], "missing": missing}


def start_job(stations):
    key = hashlib.md5(json.dumps([[s["code"], s["km"]] for s in stations]).encode()).hexdigest()
    with LOCK:
        j = JOBS.get(key)
        if j and j["state"] in ("pending", "done"):
            return key, j
        j = JOBS[key] = {"state": "pending", "msg": "looking up stations and tracing the track in OpenStreetMap...", "result": None, "t0": time.time()}

    def run():
        try:
            j["result"] = build_route(stations)
            j["state"] = "done"
        except Exception as e:
            j["state"], j["msg"] = "error", str(e)

    threading.Thread(target=run, daemon=True).start()
    return key, j
