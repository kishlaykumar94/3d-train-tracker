"""Local copy of India's railway lines (OpenStreetMap, exported by HOT as a GeoPackage) - no network needed.

Get the file once with:  python fetch_rail_data.py        (about 13 MB download, 24 MB on disk, saved to data/)
Data (c) OpenStreetMap contributors, ODbL. ways() returns the lines that touch a lat/lon box.
"""
import os, sqlite3, struct, threading

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "india_rail.gpkg")
_lock = threading.Lock()
_db = None
_env = None      # list of (minlon, maxlon, minlat, maxlat, fid)
_table = None


def available():
    return os.path.exists(PATH)


def _load():
    global _db, _env, _table
    with _lock:
        if _env is not None:
            return
        _db = sqlite3.connect(PATH, check_same_thread=False)
        t = _db.execute("select table_name from gpkg_contents where data_type='features'").fetchone()[0]
        _table = t
        env = []
        for fid, g in _db.execute(f"select fid, geom from '{t}'"):
            flags = g[3]
            if (flags >> 1) & 7 == 1:                      # envelope present: minx, maxx, miny, maxy
                env.append(struct.unpack_from("<4d", g, 8) + (fid,))
            else:                                          # no envelope: derive it from the points
                pts = _points(g)
                if pts:
                    xs, ys = [p[1] for p in pts], [p[0] for p in pts]
                    env.append((min(xs), max(xs), min(ys), max(ys), fid))
        _env = env


def _points(g):
    """GeoPackage geometry blob -> list of lines, each a list of (lat, lon). Handles LineString / MultiLineString."""
    sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    off = 8 + sizes.get((g[3] >> 1) & 7, 0)
    out = []

    def line(o, bo):
        n = struct.unpack_from(bo + "I", g, o)[0]
        o += 4
        pts = [(struct.unpack_from(bo + "d", g, o + 16 * i + 8)[0], struct.unpack_from(bo + "d", g, o + 16 * i)[0]) for i in range(n)]
        return pts, o + 16 * n

    bo = "<" if g[off] == 1 else ">"
    typ = struct.unpack_from(bo + "I", g, off + 1)[0] % 1000
    o = off + 5
    if typ == 2:
        pts, _ = line(o, bo)
        out.append(pts)
    elif typ == 5:
        cnt = struct.unpack_from(bo + "I", g, o)[0]
        o += 4
        for _ in range(cnt):
            bo2 = "<" if g[o] == 1 else ">"
            pts, o = line(o + 5, bo2)
            out.append(pts)
    return out


def ways(minlat, minlon, maxlat, maxlon):
    """All railway lines whose bounding box touches the given box. Each is a list of (lat, lon)."""
    _load()
    ids = [e[4] for e in _env if e[1] >= minlon and e[0] <= maxlon and e[3] >= minlat and e[2] <= maxlat]
    res = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = f"select geom from '{_table}' where fid in ({','.join('?' * len(chunk))})"
        for (g,) in _db.execute(q, chunk):
            res.extend(_points(g))
    return res
