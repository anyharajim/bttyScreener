"""Pulls BRC-20 market stats + newest/most active Runes from UniSat Open API into data/tokens.json.
Needs env UNISAT_API_KEY (free key from developer.unisat.io). Free tier: 5 calls/sec, 2000 calls/day.
"""
import json, os, sys, time, urllib.request, urllib.error

BASE = "https://open-api.unisat.io"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "tokens.json")
KEY = os.environ.get("UNISAT_API_KEY", "").strip()

if not KEY:
    sys.exit("UNISAT_API_KEY is empty. Add it under Settings > Secrets and variables > Actions.")


def call(path, body=None):
    """GET, or POST when body is given. Returns data['data'] or None. Logs the reason on failure."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "User-Agent": "bttyScreener", "Authorization": "Bearer " + KEY}
    if data:
        headers["Content-Type"] = "application/json"
    for i in range(3):
        try:
            req = urllib.request.Request(BASE + path, data=data, headers=headers)
            raw = urllib.request.urlopen(req, timeout=30).read().decode()
            j = json.loads(raw)
            if j.get("code") != 0:
                print("API error", path, j.get("code"), str(j.get("msg"))[:200])
                return None
            return j.get("data")
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            print("HTTP", e.code, path, msg)
            if e.code in (401, 403):  # key problem, retrying will not help
                return None
        except Exception as e:
            print("retry", path, e)
        time.sleep(2 * (i + 1))
    return None


def num(x):
    try:
        return float(x)
    except Exception:
        return 0.0


items = []

# --- BRC-20: ranked market stats (price, change, volume, market cap) ---
d = call("/v3/market/brc20/auction/brc20_types", {"timeType": "day1", "start": 0, "limit": 100})
if d:
    print("brc20 keys:", list(d.keys()), "n =", len(d.get("list") or []))
    if d.get("list"):
        print("brc20 sample:", json.dumps(d["list"][0])[:300])
    btc = num(d.get("BTCPrice"))
    seen = set()
    for r in (d.get("list") or []) + (d.get("deploy") or []):
        t = r.get("tick")
        if not t or t in seen:
            continue
        seen.add(t)
        items.append({"id": "brc20:" + t, "type": "BRC-20", "name": t,
                      "price": num(r.get("curPrice")), "change": num(r.get("changePrice")),
                      "btc_volume": num(r.get("btcVolume")), "cap": num(r.get("cap")),
                      "btc_price": btc, "deployed": 0, "supply": 0, "mint_pct": 0, "txs": 0})

# --- Runes: newest, and most active ---
for sort in ("timestamp", "transactions"):
    d = call("/v1/indexer/runes/info-list?sort=%s&start=0&limit=100" % sort)
    if not d:
        continue
    print("runes", sort, "n =", len(d.get("detail") or []), "total =", d.get("total"))
    for r in d.get("detail") or []:
        sup = num(r.get("supply"))
        cap_ = num((r.get("terms") or {}).get("cap"))
        mints = num(r.get("mints"))
        items.append({"id": "rune:" + str(r.get("runeid")), "type": "Rune",
                      "name": r.get("spacedRune") or r.get("rune"),
                      "deployed": int(r.get("timestamp") or 0), "supply": sup,
                      "mint_pct": round(mints / cap_ * 100, 2) if cap_ else 0,
                      "txs": int(r.get("transactions") or 0), "holders": int(r.get("holders") or 0)})
    time.sleep(0.5)

if not items:
    sys.exit("No data fetched from UniSat (see messages above). Data file left unchanged.")

now = int(time.time())
try:
    old = {t["id"]: t for t in json.load(open(OUT))["tokens"]}
except Exception:
    old = {}
old = {k: v for k, v in old.items() if not v.get("seed")}
for t in items:
    t["first_seen"] = old.get(t["id"], {}).get("first_seen", now)
    old[t["id"]] = t
tokens = sorted(old.values(), key=lambda t: (t.get("deployed") or 0, t["first_seen"]), reverse=True)[:800]
json.dump({"updated": now, "tokens": tokens}, open(OUT, "w"), separators=(",", ":"))
print("saved", len(tokens), "tokens;", len(items), "fetched this run")
