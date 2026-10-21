"""NTES live-status reader shared by the local server (server.py) and the Vercel function (api/status.py).

Reads NTES (enquiry.indianrail.gov.in) - session cookie + CSRF token, no captcha - and returns, for any two train numbers,
the running instances, stop-by-stop actual/projected times, non-stopping stations, last confirmed location and coach list.
Nothing about any particular train is hard-coded.
"""
import re, time, threading, datetime, urllib.request, urllib.parse, http.cookiejar

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
NTES = "https://enquiry.indianrail.gov.in/mntes"
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
TOK = re.compile(r"\d\d:\d\d \d\d-\w{3}\*?|--|-?\d+ Min|On Time|SRC|DSTN")
BACKGROUND = True      # local server refreshes stale pages in a thread; serverless must refresh inline
LOCK = threading.Lock()
HTML = {}              # train no -> (fetched_at, html)
ERR = {}               # train no -> why the last fetch failed (shown to the user)
INFLIGHT = set()


# ---------------- fetching ----------------
def fetch_html(train):
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def get(url, data=None, ref=None):
        h = {"User-Agent": UA, "Accept-Encoding": "identity"}
        if ref:
            h["Referer"] = ref
        return op.open(urllib.request.Request(url, data=data, headers=h), timeout=40).read().decode("utf-8", "ignore")

    try:
        get(NTES + "/")
        tok = get(f"{NTES}/GetCSRFToken?t={int(time.time() * 1000)}")
        n = re.search(r"name='([^']+)'", tok)
        v = re.search(r"value='([^']+)'", tok)
        if not (n and v):
            ERR[train] = "NTES did not return a session token: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tok))[:160]
            return ""
        form = urllib.parse.urlencode({"lan": "en", "jDate": datetime.datetime.now(IST).strftime("%d-%b-%Y"),
                                       "trainNo": train, "appLang": "en", n.group(1): v.group(1)}).encode()
        page = re.sub(r"\s+", " ", get(f"{NTES}/tr?opt=TrainRunning&subOpt=FindRunningInstance", form, NTES + "/"))
        if "Start Date :" not in page:
            ERR[train] = "NTES answered but listed no runs (wrong train number?): " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(style|script).*?</>", " ", page)))[:140].strip()
        else:
            ERR.pop(train, None)
        return page
    except Exception as e:
        ERR[train] = f"could not reach NTES ({type(e).__name__}: {e})"
        return ""


def _refresh(train):
    html = fetch_html(train)
    if "Start Date :" not in html:      # one retry: NTES occasionally answers a fresh session with an empty page
        time.sleep(1)
        html = fetch_html(train)
    with LOCK:
        if "Start Date :" in html:
            HTML[train] = (time.time(), html)
        INFLIGHT.discard(train)
    return html


def get_html(train):
    """Cached NTES page for a train; refreshed when older than 40 s (in the background when running locally)."""
    with LOCK:
        c = HTML.get(train)
        go = ((not c) or time.time() - c[0] > 40) and train not in INFLIGHT
        if go:
            INFLIGHT.add(train)
    if go:
        if c and BACKGROUND:
            threading.Thread(target=_refresh, args=(train,), daemon=True).start()
        else:
            return _refresh(train) or (c[1] if c else "")
    return c[1] if c else ""


# ---------------- parsing ----------------
def split_instances(html):
    marks = [(m.group(1), m.start()) for m in re.finditer(r"Start Date : (\d\d-\w{3}-\d{4})", html)]
    out = []
    for i, (start, a) in enumerate(marks):
        b = marks[i + 1][1] if i + 1 < len(marks) else len(html)
        out.append((start, html[a:b]))
    return out


def train_name(html, train):
    a = html.find("Start Date :")
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html[max(0, a - 1500):a]).replace("&nbsp;", " "))
    m = re.findall(train + r" ([^|]+?) ?\|", t)
    return m[-1].strip() if m else ""


def summarize(start, seg):
    cur = re.search(r'<h6 class ="text-primary"><b>([^<]*)</b>', seg)
    upd = re.search(r"Last Updates On</h4><font[^>]*>([^<]+)</font>", seg)
    if cur and cur.group(1).startswith("Arrived at"):      # arrived at the last station = finished
        d = parse_instance(start, seg)
        if d["rows"] and d["rows"][-1]["k"] == "stop" and d["cur"] and d["rows"][-1]["code"] == d["cur"]["code"]:
            return {"start": start, "state": "done", "text": "Reached destination", "updated": upd.group(1).strip() if upd else None}
    if cur:
        state, text = "running", cur.group(1).split(" (Delay")[0].strip()
    elif "Reached Destination" in seg[:3000]:
        state, text = "done", "Reached destination"
    elif "Yet to start" in seg[:3000]:
        state, text = "yet", "Yet to start"
    else:
        state, text = "other", "No running status"
    return {"start": start, "state": state, "text": text, "updated": upd.group(1).strip() if upd else None}


def parse_instance(start, seg):
    cur = re.search(r"<b>(Departed from|Arrived at) ([^<(]+)\((\w+)\) at (\d\d:\d\d \d\d-\w{3})[^<]*</b>", seg)
    upd = re.search(r"Last Updates On</h4><font[^>]*>([^<]+)</font>", seg)
    coaches = []
    for mod in re.finditer(r"Coach Position :", seg):
        labels = re.findall(r'<div style="width: 40px;height:18px[^>]*><b>([^<]*)</b>', seg[mod.start():mod.start() + 12000])
        if len(labels) > 4:
            if labels.count("ENG") > 1:            # a second ENG means the list runs on into another rake
                labels = labels[: labels.index("ENG", 1)]
            coaches = labels
            break
    rows = []
    for ch in re.split(r'(?=<div class=" w3-card-2 )', seg)[1:]:
        cls = re.match(r'<div class=" w3-card-2 ([^"]*)"', ch)
        if not cls:
            continue
        cls = cls.group(1)
        ch = ch.split("<!-- Modal -->")[0]
        t = re.sub(r"(\| ?)+", "|", re.sub(r"<[^>]+>", "|", ch.replace("&nbsp;", " ")))
        km = re.search(r"\|(\d+)\|KMs", t)
        if "nonStopRow" in cls:
            m = re.search(r"\|\s*([^|]*?) - (\w+) \|(\d+)\|KMs", t)
            if m and "Non-Stopping" in t:
                rows.append({"k": "pass", "name": m.group(1).strip(), "code": m.group(2), "km": int(m.group(3))})
        elif "stopRow" in cls:
            toks_l = TOK.findall(t[: km.start()] if km else t)
            toks_r = TOK.findall(t[km.end():] if km else "")
            nm = re.search(r"\|([A-Z][A-Z0-9 .'&()-]+?)\|(\w+) ?\|", re.sub(r"\d\d:\d\d \d\d-\w{3}\*?", "", t[: km.start()] if km else t))
            name = nm.group(1).strip() if nm else "?"
            code = nm.group(2) if nm else "?"
            if toks_l[:1] == ["SRC"]:
                toks_l = [None, None, None] + toks_l[2:]
            if toks_r[:1] == ["DSTN"]:
                toks_r = [None, None, None]
            g = lambda L, i: (L[i] if i < len(L) and L[i] not in ("--", "SRC", "DSTN") else None)
            rows.append({"k": "stop", "name": name, "code": code, "km": int(km.group(1)) if km else 0,
                         "sa": g(toks_l, 0), "aa": g(toks_l, 1), "da": g(toks_l, 2),
                         "sd": g(toks_r, 0), "ad": g(toks_r, 1), "dd": g(toks_r, 2)})
    return {"start": start, "updated": upd.group(1).strip() if upd else None, "coaches": coaches,
            "cur": ({"kind": cur.group(1).split()[0], "name": cur.group(2).strip(), "code": cur.group(3), "time": cur.group(4)} if cur else None),
            "rows": rows}


def pick_default(inst):
    running = [i for i in inst if i["state"] == "running"]
    if running:
        return max(running, key=lambda i: datetime.datetime.strptime(i["start"], "%d-%b-%Y"))["start"]
    done = [i for i in inst if i["state"] == "done"]
    if done:
        return max(done, key=lambda i: datetime.datetime.strptime(i["start"], "%d-%b-%Y"))["start"]
    return inst[0]["start"] if inst else None


def train_status(train, want):
    train = (train or "").strip()
    if not re.fullmatch(r"\d{5}", train):
        return {"train": train, "error": "Enter a 5-digit train number"}
    html = get_html(train)
    segs = split_instances(html)
    if not segs:
        return {"train": train, "error": f"No data for {train}: " + ERR.get(train, "NTES returned no running instances")}
    inst = [summarize(s, g) for s, g in segs]
    start = want if want in [i["start"] for i in inst] else pick_default(inst)
    seg = dict(segs)[start]
    d = parse_instance(start, seg)
    d.update({"train": train, "name": train_name(html, train), "instances": inst, "fetched": datetime.datetime.now(IST).strftime("%d %b %H:%M:%S")})
    return d


def km_offset(da, db):
    """Median km difference (B minus A) over stations both trains' rows list - maps B's km onto A's."""
    ka = {r["code"]: r["km"] for r in da["rows"]}
    diffs = sorted(r["km"] - ka[r["code"]] for r in db["rows"] if r["code"] in ka)
    return diffs[len(diffs) // 2] if len(diffs) >= 2 else None


def cur_km(d):
    if not d["cur"]:
        return None
    r = next((r for r in d["rows"] if r["code"] == d["cur"]["code"]), None)
    return r["km"] if r else None


def auto_pair(a, b):
    """Pick the running run of each train that are closest to each other along their shared route."""
    ha, hb = get_html(a), get_html(b)
    sa = [(s, g) for s, g in split_instances(ha) if summarize(s, g)["state"] == "running"]
    sb = [(s, g) for s, g in split_instances(hb) if summarize(s, g)["state"] == "running"]
    best = None
    for s1, g1 in sa:
        d1 = parse_instance(s1, g1)
        for s2, g2 in sb:
            d2 = parse_instance(s2, g2)
            off, k1, k2 = km_offset(d1, d2), cur_km(d1), cur_km(d2)
            if off is None or k1 is None or k2 is None:
                continue
            gap = abs(k1 - (k2 - off))
            if best is None or gap < best[0]:
                best = (gap, s1, s2)
    return (best[1], best[2]) if best else (None, None)


def api_status(q):
    """q: query dict of lists, as from urllib.parse.parse_qs. Returns {"a": ..., "b": ...}."""
    g = lambda k: (q.get(k) or [None])[0]
    res = {}
    if re.fullmatch(r"\d{5}", g("a") or "") and re.fullmatch(r"\d{5}", g("b") or "") and not g("as") and not g("bs"):
        q = dict(q)
        q["as"], q["bs"] = [[x] if x else [None] for x in auto_pair(g("a"), g("b"))]
    ths = [threading.Thread(target=lambda k=k, n=n, s=s: res.__setitem__(k, train_status(n, s)))
           for k, n, s in (("a", g("a"), (q.get("as") or [None])[0]), ("b", g("b"), (q.get("bs") or [None])[0]))]
    [t.start() for t in ths]
    [t.join() for t in ths]
    return res
