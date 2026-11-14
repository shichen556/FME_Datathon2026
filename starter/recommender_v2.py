"""Recommender v2: session-aware ranking on top of the starter's pull → predict → push loop.

    python starter/recommender_v2.py     # same .env as starter/recommender.py

What the history says (shop.history_sessions, 2M impressions):
- A product the shopper viewed earlier in the session, shown in slot 1, is bought ~17x more often
  than any other product in slot 1 (6.3% vs 0.37%).
- Products bought in the same sessions where a viewed product was viewed (view → purchase
  co-occurrence in shop.history_events) are bought ~7x more often than the rest.
- Slot 1 gets ~2x the purchases of slot 2 and ~9x those of slot 10: the order matters.

So each list is: the session's viewed products (minus ones this shopper already bought), then
products co-purchased with them, then best sellers of the viewed subcategories, then what sells
right now (history + live shop.events). Shoppers without views get the live best sellers.
Everything heavy is computed in RawTree in SQL and refreshed in the background, so answering a
request is pure Python on in-memory dicts (well under 1 ms).
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

# Self-contained (no import from recommender.py), so this file works under any name.
# .env is searched in the current directory and in the repo root (one level above starter/).
for env in (Path(".env"), Path(__file__).resolve().parent.parent / ".env"):
    if env.exists():
        for line in env.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() and not key.strip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip())
        break
API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com")
TEAM = os.environ["TEAM_ID"]
http = requests.Session()
http.headers["Authorization"] = f"Bearer {os.environ['RAWTREE_API_KEY']}"

Record = dict[str, Any]
"""RawTree returns rows as JSON objects: {"column": value, ...}"""

MODEL_VERSION = "v2-session-covis"

OUT_OF_STOCK = """
SELECT product_id::String AS product_id
FROM shop.catalog_updates
WHERE change::String IN ('out_of_stock', 'back_in_stock')
GROUP BY product_id
HAVING argMax(change::String, ts::DateTime64(3)) = 'out_of_stock'"""
"""Products whose latest stock change is a stock-out."""


def query(sql: str) -> list[Record]:
    r = http.post(f"{API}/v1/query", json={"sql": sql}, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def out_of_stock() -> set[str]:
    """Products out of stock right now. Recommending one makes the whole answer invalid."""
    return {r["product_id"] for r in query(OUT_OF_STOCK)}


def push(answers: list[Record]) -> None:
    """Batch insert into team_NN.submissions."""
    http.post(f"{API}/v1/tables/submissions", params={"database": TEAM}, json=answers, timeout=10).raise_for_status()
    print(f"answered {len(answers)}")

# ---------------------------------------------------------------- SQL (runs inside RawTree)

COVIS = """
WITH v AS (SELECT DISTINCT session_id::String AS s, product_id::String AS a FROM {events} WHERE event_type = 'view'{cut}),
     p AS (SELECT DISTINCT session_id::String AS s, product_id::String AS b FROM {events} WHERE event_type = 'purchase'{cut})
SELECT a, b, count() AS n
FROM v INNER JOIN p ON v.s = p.s
WHERE a != b
GROUP BY a, b ORDER BY n DESC LIMIT 30 BY a"""
"""For each product a, the 30 products most often bought in sessions where a was viewed."""

SALES = """
SELECT product_id::String AS product_id,
       countIf(ts::DateTime64(3) >= {recent_from}) AS recent,
       count() AS total
FROM {events}
WHERE event_type = 'purchase'{cut}
GROUP BY product_id"""
"""Purchases per product: all-time and in the most recent window (trend)."""

CATALOG = """
SELECT product_id, argMax(subcategory, v) AS subcategory, argMax(is_active, v) AS is_active
FROM (
    SELECT product_id::String AS product_id, subcategory::String AS subcategory, is_active::Bool AS is_active, '' AS v
    FROM shop.catalog
    UNION ALL
    SELECT product_id::String, subcategory::String, is_active::Bool, toString(ts)
    FROM shop.catalog_updates
)
GROUP BY product_id"""
"""Current catalogue: subcategory and is_active with the latest update applied."""

RECENT_BUYERS = """
SELECT user_id::String AS user_id, product_id::String AS product_id
FROM shop.events
WHERE event_type = 'purchase' AND ts::DateTime64(3) > now() - INTERVAL 6 HOUR
UNION ALL
SELECT r.user_id::String, f.purchased::String
FROM {team}.feedback AS f
INNER JOIN shop.requests AS r ON r.request_id::String = f.request_id::String
WHERE f.purchased::String != '' AND f.ts::DateTime64(3) > now() - INTERVAL 6 HOUR"""
"""Who bought what in the last hours (organic + our carousel): shoppers rarely rebuy."""

NEW_REQUESTS = """
SELECT request_id, user_id, recent_views
FROM shop.requests
ORDER BY ts DESC
LIMIT 50"""


# ---------------------------------------------------------------- model

@dataclass
class Model:
    covis: dict[str, list[tuple[str, float]]] = field(default_factory=dict)  # a -> [(b, weight)], best first
    popular: list[str] = field(default_factory=list)                        # global ranking, best first
    popular_by_sub: dict[str, list[str]] = field(default_factory=dict)      # subcategory -> ranking
    subcategory: dict[str, str] = field(default_factory=dict)               # product -> subcategory
    inactive: set[str] = field(default_factory=set)
    unavailable: set[str] = field(default_factory=set)                       # out of stock right now
    bought: dict[str, set[str]] = field(default_factory=dict)               # user -> products bought lately

    def blocked(self, user: str | None) -> set[str]:
        return self.inactive | self.unavailable | (self.bought.get(user, set()) if user else set())


def load_covis(cut: str = "", live: bool = True) -> dict[str, list[tuple[str, float]]]:
    sources = ["shop.history_events"] + (["shop.events"] if live else [])
    counts: Counter[tuple[str, str]] = Counter()
    for events in sources:
        for r in query(COVIS.format(events=events, cut=cut)):
            counts[r["a"], r["b"]] += int(r["n"])
    covis: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (a, b), n in counts.items():
        covis[a].append((b, n))
    out = {}
    for a, lst in covis.items():
        lst.sort(key=lambda x: -x[1])
        top = lst[0][1]
        out[a] = [(b, n / top) for b, n in lst[:30]]  # normalised: best co-purchase = 1
    return out


def load_popularity(cut: str = "", live: bool = True, until: str | None = None) -> Counter[str]:
    """Score = all-time purchases + 5x purchases in the last 7 days (+ live purchases, 20x)."""
    score: Counter[str] = Counter()
    recent_from = f"toDateTime64('{until}', 3) - INTERVAL 7 DAY" if until else \
        "(SELECT max(ts::DateTime64(3)) FROM shop.history_events) - INTERVAL 7 DAY"
    for r in query(SALES.format(events="shop.history_events", cut=cut, recent_from=recent_from)):
        score[r["product_id"]] += int(r["total"]) + 5 * int(r["recent"])
    if live:
        for r in query(SALES.format(events="shop.events", cut="", recent_from="now() - INTERVAL 3 HOUR")):
            score[r["product_id"]] += 20 * int(r["total"]) + 40 * int(r["recent"])
    return score


def build_model(cut_date: str | None = None, live: bool = True) -> Model:
    """cut_date ('YYYY-MM-DD') restricts history for offline evaluation; live adds shop.events."""
    cut = f" AND ts::DateTime64(3) < '{cut_date}'" if cut_date else ""
    m = Model()
    for r in query(CATALOG):
        m.subcategory[r["product_id"]] = r["subcategory"]
        if not r["is_active"]:
            m.inactive.add(r["product_id"])
    m.covis = load_covis(cut, live)
    score = load_popularity(cut, live, cut_date)
    for p in m.subcategory:
        score.setdefault(p, 0)
    m.popular = [p for p, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))]
    by_sub: dict[str, list[str]] = defaultdict(list)
    for p in m.popular:
        by_sub[m.subcategory.get(p, "")].append(p)
    m.popular_by_sub = dict(by_sub)
    return m


# ---------------------------------------------------------------- ranking

def recommend(recent_views: list[Record] | None, model: Model, user: str | None = None, k: int = 10) -> list[str]:
    blocked = model.blocked(user)
    views = [v["product_id"] for v in (recent_views or [])]
    out: list[str] = []

    def add(p: str) -> bool:
        if p not in blocked and p not in out:
            out.append(p)
        return len(out) >= k

    # 1. products viewed in this session: most viewed first, then most recent
    view_count = Counter(views)
    last_seen = {p: i for i, p in enumerate(views)}
    for p in sorted(view_count, key=lambda p: (-view_count[p], -last_seen[p])):
        if add(p):
            return out

    # 2. co-purchased with the viewed products, recent views weigh more
    score: Counter[str] = Counter()
    for age, p in enumerate(reversed(views)):
        for b, w in model.covis.get(p, []):
            score[b] += w * 0.8 ** age
    for p, _ in score.most_common():
        if add(p):
            return out

    # 3. best sellers of the viewed subcategories (covers new products with no co-purchases yet)
    subs = list(dict.fromkeys(model.subcategory.get(p) for p in reversed(views) if model.subcategory.get(p)))
    for sub in subs:
        for p in model.popular_by_sub.get(sub, [])[:5]:
            if add(p):
                return out

    # 4. what sells overall (live trend included)
    for p in model.popular:
        if add(p):
            return out
    return out


# ---------------------------------------------------------------- live loop

class Refresher(threading.Thread):
    """Rebuilds the slow parts in the background so the answer loop never waits for them."""

    def __init__(self, model: Model):
        super().__init__(daemon=True)
        self.model = model

    def run(self) -> None:
        last_full = time.time()
        while True:
            try:
                self.model.unavailable = out_of_stock()
                bought: dict[str, set[str]] = defaultdict(set)
                for r in query(RECENT_BUYERS.format(team=TEAM)):
                    bought[r["user_id"]].add(r["product_id"])
                self.model.bought = dict(bought)
                if time.time() - last_full > 600:  # co-purchases, popularity, catalogue: every 10 min
                    fresh = build_model()
                    fresh.unavailable, fresh.bought = self.model.unavailable, self.model.bought
                    self.model.__dict__.update(fresh.__dict__)
                    last_full = time.time()
                    print("model refreshed")
            except Exception as e:
                print(f"refresh failed (keeping the last model): {e}")
            time.sleep(2)


def main() -> None:
    model = build_model()
    model.unavailable = out_of_stock()
    print(f"model ready: {len(model.covis)} products with co-purchases, {len(model.inactive)} inactive")
    Refresher(model).start()
    seen: set[str] = set()
    while True:
        try:
            fresh = [r for r in query(NEW_REQUESTS) if r["request_id"] not in seen]
            if fresh:
                answers = []
                for r in fresh:
                    seen.add(r["request_id"])
                    answers.append({"request_id": r["request_id"],
                                    "items": recommend(r.get("recent_views"), model, r.get("user_id")),
                                    "model_version": MODEL_VERSION})
                push(answers)
        except Exception as e:  # keep running: shoppers keep arriving while you sleep
            print(f"error: {e}")
            time.sleep(1)
        time.sleep(0.3)


if __name__ == "__main__":
    main()
