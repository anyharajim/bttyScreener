"""Builds data/tokens.json from the UniSat Open API (free key: developer.unisat.io).
Env: UNISAT_API_KEY. Free tier = 5 calls/sec, 2000 calls/day. This job uses ~50 calls per run.
Sources:
  - BRC-20 market stats (price, cap, holders, deploy time) for the top 100 tickers
  - Newest BRC-20 deployments (list tail + per-ticker info: supply, minted, holders)
  - Runes: newest and most active (info-list)
"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse

BASE = "https://open-api.unisat.io"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "tokens.json")
KEY = os.environ.get("UNISAT_API_KEY", "").strip()
NEW_BRC20 = 40  # how many of the newest BRC-20 tickers to look up

if not KEY:
    sys.exit("UNISAT_API_KEY is empty. Add it under Settings > Secrets and variables > Actions.")


def call(path, body=None):
    """GET, or POST when body is given. Returns the 'data' field or None (reason is printed)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "User-Agent": "bttyScreener", "Authorization": "Bearer " + KEY}
    if data:
        headers["Content-Type"] = "application/json"
    for i in range(3):
        try:
            req = urllib.request.Request(BASE + path, data=data, headers=headers)
            j = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
            if j.get("code") != 0:
                print("API error", path[:60], j.get("code"), str(j.get("msg"))[:160])
                return None
            return j.get("data")
        except urllib.error.HTTPError as e:
            print("HTTP", e.code, path[:60], e.read().decode()[:160])
            if e.code in (401, 403, 404):
                return None
        except Exception as e:
            print("retry", path[:60], e)
        time.sleep(2 * (i + 1))
    return None


def num(x):
    try:
        return float(x)
    except Exception:
        return 0.0


items = {}


def add(t):
    old = items.get(t["id"], {})
    for k, v in t.items():
        if v not in (None, 0, "") or k not in old:
            old[k] = v
    items[t["id"]] = old


# 1) BRC-20 market stats --------------------------------------------------
d = call("/v3/market/brc20/auction/brc20_types", {"timeType": "day1", "start": 0, "limit": 100})
if d:
    btc = num(d.get("BTCPrice"))
    print("brc20 market:", len(d.get("list") or []), "BTC", btc)
    for r in d.get("list") or []:
        tick = r.get("tick")
        if not tick:
            continue
        price_usd = num(r.get("curPrice")) * btc / 1e8 if btc > 1000 else None
        add({"id": "brc20:" + tick, "type": "BRC-20", "name": tick,
             "deployed": int(num(r.get("deployTime"))), "holders": int(num(r.get("holders"))),
             "price_usd": price_usd, "change": num(r.get("changePercent")),
             "cap_usd": num(r.get("capUSD")), "mint_pct": None, "txs": 0})
time.sleep(0.4)

# 2) Newest BRC-20 deployments --------------------------------------------
d = call("/v1/indexer/brc20/list?start=0&limit=1")
total = int(num((d or {}).get("total")))
print("brc20 total tickers:", total)
if total > NEW_BRC20:
    d = call("/v1/indexer/brc20/list?start=%d&limit=%d" % (total - NEW_BRC20, NEW_BRC20))
    detail = (d or {}).get("detail") or []
    print("brc20 list tail:", len(detail), "sample:", json.dumps(detail[:2])[:200])
    ticks = []
    for x in detail:
        t = x if isinstance(x, str) else (x.get("ticker") or x.get("tick") or "")
        if t:
            ticks.append(t)
    times = []
    for t in ticks:
        if not t.isalnum():
            continue  # special-character tickers need hex paths; skip
        time.sleep(0.25)
        info = call("/v1/indexer/brc20/%s/info" % urllib.parse.quote(t))
        if not info:
            continue
        mx, mn = num(info.get("max")), num(info.get("totalMinted") or info.get("minted"))
        dep = int(num(info.get("deployBlocktime")))
        times.append(dep)
        add({"id": "brc20:" + (info.get("ticker") or t), "type": "BRC-20", "name": info.get("ticker") or t,
             "deployed": dep, "holders": int(num(info.get("holdersCount"))),
             "mint_pct": round(mn / mx * 100, 2) if mx else None, "txs": int(num(info.get("historyCount")))})
    if times:
        print("newest brc20 deploy times: min", min(times), "max", max(times))

# 3) Runes -----------------------------------------------------------------
for sort in ("timestamp", "transactions"):
    time.sleep(0.4)
    d = call("/v1/indexer/runes/info-list?sort=%s&start=0&limit=100" % sort)
    if not d:
        continue
    print("runes", sort, len(d.get("detail") or []), "of", d.get("total"))
    for r in d.get("detail") or []:
        cap_ = num((r.get("terms") or {}).get("cap"))
        mints = num(r.get("mints"))
        add({"id": "rune:" + str(r.get("runeid")), "type": "Rune", "name": r.get("spacedRune") or r.get("rune"),
             "deployed": int(num(r.get("timestamp"))), "holders": int(num(r.get("holders"))),
             "mint_pct": round(min(mints / cap_ * 100, 100), 2) if cap_ else None,
             "txs": int(num(r.get("transactions")))})

if not items:
    sys.exit("No data fetched from UniSat (see messages above). Data file left unchanged.")

now = int(time.time())
try:
    old = {t["id"]: t for t in json.load(open(OUT))["tokens"]}
except Exception:
    old = {}
for k, t in items.items():
    t["first_seen"] = old.get(k, {}).get("first_seen", now)
    old[k] = t
tokens = sorted(old.values(), key=lambda t: t.get("deployed") or 0, reverse=True)[:800]
json.dump({"updated": now, "tokens": tokens}, open(OUT, "w"), separators=(",", ":"))
print("saved", len(tokens), "tokens;", len(items), "fetched this run")
