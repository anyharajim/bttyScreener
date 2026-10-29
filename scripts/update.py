"""Pulls BRC-20 tokens + Runes from Hiro's free API into data/tokens.json."""
import json, time, urllib.request, os
H = "https://api.hiro.so"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "tokens.json")

def get(path):
    for i in range(3):
        try:
            req = urllib.request.Request(H + path, headers={"Accept": "application/json", "User-Agent": "bttyScreener", "x-api-key": os.environ.get("HIRO_API_KEY", "")})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:
            print("retry", path, e); time.sleep(3 * (i + 1))
    return {"results": [], "total": 0}

def sec(t):
    t = float(t or 0)
    return int(t / 1000) if t > 1e11 else int(t)

def num(x):
    try: return float(x)
    except: return 0.0

def brc20(r):
    mx, mn = num(r.get("max_supply")), num(r.get("minted_supply"))
    return {"id": "brc20:" + r["ticker"], "type": "BRC-20", "name": r["ticker"],
            "deployed": sec(r.get("deploy_timestamp")), "supply": mx,
            "mint_pct": round(mn / mx * 100, 2) if mx else 0, "txs": r.get("tx_count", 0)}

def rune(r):
    s = r.get("supply") or {}
    return {"id": "rune:" + r["id"], "type": "Rune", "name": r.get("spaced_name") or r.get("name"),
            "deployed": sec((r.get("location") or {}).get("timestamp")), "supply": num(s.get("current")),
            "mint_pct": round(num(s.get("mint_percentage")), 2), "txs": s.get("total_mints", 0)}

items = []
items += [brc20(r) for r in get("/ordinals/v1/brc-20/tokens?limit=60&order_by=tx_count")["results"]]
total = get("/ordinals/v1/brc-20/tokens?limit=1").get("total", 0)
if total:
    items += [brc20(r) for r in get(f"/ordinals/v1/brc-20/tokens?limit=60&offset={max(total-60,0)}")["results"]]
items += [rune(r) for r in get("/runes/v1/etchings?limit=60")["results"]]

now = int(time.time())
try: old = {t["id"]: t for t in json.load(open(OUT))["tokens"]}
except Exception: old = {}
for t in items:
    t["first_seen"] = old.get(t["id"], {}).get("first_seen", now)
    old[t["id"]] = t
tokens = sorted(old.values(), key=lambda t: t["deployed"], reverse=True)[:600]
json.dump({"updated": now, "tokens": tokens}, open(OUT, "w"), separators=(",", ":"))
print("saved", len(tokens))
