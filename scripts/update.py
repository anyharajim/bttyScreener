"""Builds data/tokens.json from the UniSat Open API (free key: developer.unisat.io).
Env: UNISAT_API_KEY. Free tier = 5 calls/sec, 2000 calls/day. This job uses ~50 calls per run.
Sources:
  - BRC-20 market stats (price, cap, holders, deploy time) for the top 100 tickers
  - Newest BRC-20 deployments (list tail + per-ticker info: supply, minted, holders)
  - Runes: newest and most active (info-list)
"""
import json, os, re, sys, time, urllib.request, urllib.error, urllib.parse

BASE = "https://open-api.unisat.io"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUT = os.path.join(DATA, "tokens.json")
OUT2 = os.path.join(DATA, "coins.json")
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



def norm(s):
    s = re.sub(r"\((runes|bitcoin)\)", "", str(s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


# CoinGecko names do not always match the on-chain rune name; these ids are mapped by hand.
RUNE_OVERRIDE = {
    "dog-go-to-the-moon-rune": "doggotothemoon",
    "billion-dollar-cat-runes": "billiondollarcat",
    "magic-internet-money-runes": "magicinternetmoney",
    "satoshi-nakamoto-rune": "satoshinakamoto",
    "gizmo-imaginary-kitten-runes": "gizmoimaginarykitten",
    "rune-pups": "pupsworldpeace",
}
B20_ALIAS = {"1000sats": "sats"}  # CoinGecko's 1000SATS is the on-chain 'sats' ticker


def cg(category, pages=2):
    """CoinGecko markets list for a category (id, symbol, name, image). Returns [] if blocked."""
    out = []
    for p in range(1, pages + 1):
        url = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=%s"
               "&order=market_cap_desc&per_page=250&page=%d&sparkline=false" % (category, p))
        d = None
        for i in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "bttyScreener", "Accept": "application/json"})
                d = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
                break
            except Exception as e:
                print("CoinGecko", category, "attempt", i + 1, e)
                time.sleep(15 * (i + 1))
        if not d:
            break
        out += d
        if len(d) < 250:
            break
        time.sleep(8)
    print("coingecko", category, len(out))
    return out


try:
    prev = {t["id"]: t for t in json.load(open(OUT))["tokens"]}
except Exception:
    prev = {}
try:
    prev_cg = json.load(open(OUT2))
except Exception:
    prev_cg = {}

# 0) CoinGecko lists (photos + which coins are BRC-20 / Runes) ---------------
cg_b20 = cg("brc-20")
time.sleep(8)
cg_rn = cg("runes")
if not cg_b20 and not cg_rn:
    print("CoinGecko unavailable; keeping previous photo/member lists")
rn_over_img = {RUNE_OVERRIDE[c["id"]]: c.get("image") for c in cg_rn if c["id"] in RUNE_OVERRIDE and c.get("image")}
b20_img = {str(c["symbol"]).lower(): c.get("image") for c in cg_b20 if c.get("image")}
rn_img = dict(rn_over_img)
for c in cg_rn:
    for k in (norm(c.get("name")), norm(c.get("symbol"))):
        if k and c.get("image"):
            rn_img[k] = c["image"]

brc_cache = {}


def brc20_item(t):
    """Look up a BRC-20 ticker; returns dict or None. Finished tokens are not looked up again."""
    key = t.lower()
    if key in brc_cache:
        return brc_cache[key]
    old = prev.get("brc20:" + t) or {}
    if (old.get("mint_pct") or 0) >= 100 and old.get("holders"):
        brc_cache[key] = None
        return None
    if not t.isalnum():
        return None
    time.sleep(0.25)
    info = call("/v1/indexer/brc20/%s/info" % urllib.parse.quote(t))
    if not info:
        return None
    mx, mn = num(info.get("max")), num(info.get("totalMinted") or info.get("minted"))
    r = {"id": "brc20:" + (info.get("ticker") or t), "type": "BRC-20", "name": info.get("ticker") or t,
         "deployed": int(num(info.get("deployBlocktime"))), "holders": int(num(info.get("holdersCount"))),
         "mint_pct": round(mn / mx * 100, 2) if mx else None, "txs": int(num(info.get("historyCount")))}
    brc_cache[key] = r
    return r


# 1) BRC-20 market stats (top 100) + BTTY -----------------------------------
btc = 0.0
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
             "cap_usd": num(r.get("capUSD")), "txs": 0})
time.sleep(0.4)

btty = dict(prev_cg.get("btty") or {})
d = call("/v3/market/brc20/auction/brc20_types", {"timeType": "day1", "start": 0, "limit": 5, "ticks": ["btty"]})
if d:
    btc = btc or num(d.get("BTCPrice"))
    print("BTTY raw:", json.dumps((d.get("list") or [])[:1])[:400])
    for r in d.get("list") or []:
        if str(r.get("tick")).lower() == "btty":
            btty.update({"price_usd": num(r.get("curPrice")) * btc / 1e8 if btc > 1000 else None,
                         "change": num(r.get("changePercent")), "cap_usd": num(r.get("capUSD")),
                         "holders": int(num(r.get("holders")))})
time.sleep(0.4)
bi = brc20_item("btty")
if bi:
    btty["holders"] = bi["holders"] or btty.get("holders")
    btty["mint_pct"] = bi["mint_pct"]
print("BTTY:", btty)

# 2) Mint status for top-100 market tickers, CoinGecko BRC-20 coins, newest deployments
want = [k.split(":", 1)[1] for k in items if k.startswith("brc20:")]
want += [B20_ALIAS.get(str(c["symbol"]).lower(), str(c["symbol"])) for c in cg_b20]
d = call("/v1/indexer/brc20/list?start=0&limit=1")
total = int(num((d or {}).get("total")))
print("brc20 total tickers:", total)
if total > NEW_BRC20:
    d = call("/v1/indexer/brc20/list?start=%d&limit=%d" % (total - NEW_BRC20, NEW_BRC20))
    for x in (d or {}).get("detail") or []:
        t = x if isinstance(x, str) else (x.get("ticker") or x.get("tick") or "")
        if t:
            want.append(t)
seen = set()
minted_b20 = {}
for t in want:
    if t.lower() in seen:
        continue
    seen.add(t.lower())
    r = brc20_item(t)
    if r:
        add(r)
def pct_of(sym):
    best = None
    for src in (items, prev):
        for k, v in src.items():
            if k.lower() == "brc20:" + sym and v.get("mint_pct") is not None:
                best = max(best or 0, v["mint_pct"])
    return best


for c in cg_b20:  # minted flag for each CoinGecko BRC-20 coin
    p = pct_of(B20_ALIAS.get(str(c["symbol"]).lower(), str(c["symbol"]).lower()))
    minted_b20[c["id"]] = (p is not None and p >= 100)

# 3) Runes -----------------------------------------------------------------
runes_all = []
for st in (0, 500):
    time.sleep(0.4)
    d = call("/v1/indexer/runes/info-list?sort=holders&start=%d&limit=500" % st)
    runes_all += (d or {}).get("detail") or []
print("runes by holders:", len(runes_all))


def rune_done(r):
    if r.get("mintable") is not None:
        return not r.get("mintable")
    cap_ = num((r.get("terms") or {}).get("cap"))
    return cap_ == 0 or num(r.get("mints")) >= cap_


by_norm = {norm(r.get("spacedRune") or r.get("rune")): r for r in runes_all}
if runes_all:
    print("rune sample keys:", sorted(runes_all[0].keys()))
minted_rn = {}
for c in cg_rn:
    r = (by_norm.get(RUNE_OVERRIDE.get(c["id"], "")) or by_norm.get(norm(c.get("name")))
         or by_norm.get(norm(c.get("symbol"))))
    ok = bool(r and rune_done(r))
    minted_rn[c["id"]] = ok
    print("rune", c["id"], "|", c.get("name"), "|", c.get("symbol"), "| matched:", bool(r),
          "| mintable:", (r or {}).get("mintable"), "mints:", (r or {}).get("mints"),
          "cap:", ((r or {}).get("terms") or {}).get("cap"), "->", ok)

d = call("/v1/indexer/runes/info-list?sort=timestamp&start=0&limit=1")
rtotal = int(num((d or {}).get("total")))
queries = [("transactions", 0)]
if rtotal > 100:
    queries.append(("timestamp", rtotal - 100))  # oldest-first list: newest runes are at the end
for sort, start in queries:
    time.sleep(0.4)
    d = call("/v1/indexer/runes/info-list?sort=%s&start=%d&limit=100" % (sort, start))
    if not d:
        continue
    for r in d.get("detail") or []:
        cap_ = num((r.get("terms") or {}).get("cap"))
        mints = num(r.get("mints"))
        add({"id": "rune:" + str(r.get("runeid")), "type": "Rune", "name": r.get("spacedRune") or r.get("rune"),
             "deployed": int(num(r.get("timestamp"))), "holders": int(num(r.get("holders"))),
             "mint_pct": round(min(mints / cap_ * 100, 100), 2) if cap_ else 100.0,
             "txs": int(num(r.get("transactions")))})

if not items:
    sys.exit("No data fetched from UniSat (see messages above). Data file left unchanged.")

# merge + photos ------------------------------------------------------------
now = int(time.time())
old = dict(prev)
for k, t in items.items():
    t["first_seen"] = old.get(k, {}).get("first_seen", now)
    old[k] = {**old.get(k, {}), **t}
for t in old.values():
    img = b20_img.get(str(t.get("name")).lower()) if t.get("type") == "BRC-20" else rn_img.get(norm(t.get("name")))
    if img:
        t["image"] = img
tokens = sorted(old.values(), key=lambda t: t.get("deployed") or 0, reverse=True)[:800]
json.dump({"updated": now, "tokens": tokens}, open(OUT, "w"), separators=(",", ":"))

members = {}
if cg_b20 or cg_rn:
    for c in cg_b20:
        members[c["id"]] = {"t": "BRC-20", "minted": minted_b20.get(c["id"], False)}
    for c in cg_rn:
        members[c["id"]] = {"t": "Rune", "minted": minted_rn.get(c["id"], False)}
else:
    members = prev_cg.get("members") or {}
json.dump({"updated": now, "btty": btty, "members": members}, open(OUT2, "w"), separators=(",", ":"))
print("saved", len(tokens), "tokens;", len(items), "fetched;", len(members), "coin members,",
      sum(1 for m in members.values() if m["minted"]), "fully minted")
