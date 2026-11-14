"""Baseline recommender: the all-time best sellers that are in stock.

    python starter/recommender.py        # reads TEAM_ID and RAWTREE_API_KEY from .env or the environment

pull → predict → push: it polls shop.requests, answers every new request and inserts the
answers in batches into team_NN.submissions. recommend() is the part to replace: it is
exactly what the leaderboard calls "baseline", and what shoppers see when an answer is
missing, late or invalid (the fallback).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

for line in Path(".env").read_text().splitlines() if Path(".env").exists() else []:
    key, _, value = line.partition("=")
    os.environ.setdefault(key.strip(), value.strip())
API = os.environ.get("RAWTREE_API_URL", "https://api.rawtree.com")
TEAM = os.environ["TEAM_ID"]
http = requests.Session()
http.headers["Authorization"] = f"Bearer {os.environ['RAWTREE_API_KEY']}"

SALES = """
SELECT product_id, count() AS n
FROM shop.history_events
WHERE event_type = 'purchase'{sales}
GROUP BY product_id"""
"""How many times each product was bought in the historical events."""

NEW_REQUESTS = """
SELECT request_id, recent_views
FROM shop.requests
ORDER BY ts DESC
LIMIT 50"""
"""The 50 most recent recommendation requests, newest first."""

OUT_OF_STOCK = """
SELECT product_id::String AS product_id
FROM shop.catalog_updates
WHERE change::String IN ('out_of_stock', 'back_in_stock')
GROUP BY product_id
HAVING argMax(change::String, ts::DateTime64(3)) = 'out_of_stock'"""
"""Products whose latest stock change is a stock-out."""

Record = dict[str, Any]
"""RawTree returns rows as JSON objects: {"column": value, ...}"""


def query(sql: str) -> list[Record]:
    r = http.post(f"{API}/v1/query", json={"sql": sql}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]


def best_sellers(until: str | None = None) -> list[str]:
    """Every product ever bought, best-selling first (ties: higher product_id first).

    `until` ('YYYY-MM-DD') restricts the history the ranking is built from, for offline
    evaluation. Live it is computed once, at start: the ranking never refreshes.
    """
    sales_cut = f" AND ts < '{until}'" if until else ""
    sales = sorted(((int(r["n"]), r["product_id"]) for r in query(SALES.format(sales=sales_cut))), reverse=True)
    return [product for _, product in sales]


def out_of_stock() -> set[str]:
    """Products out of stock right now. Recommending one makes the whole answer invalid."""
    return {r["product_id"] for r in query(OUT_OF_STOCK)}


def pull(seen: set[str]) -> list[Record]:
    """New shop.requests records not answered yet."""
    fresh = []
    for req in query(NEW_REQUESTS):
        if req["request_id"] not in seen:
            seen.add(req["request_id"])
            fresh.append(req)
    return fresh


def predict(requests: list[Record], best: list[str], unavailable: set[str]) -> list[Record]:
    """One submission per request."""
    return [{"request_id": req["request_id"],
             "items": recommend(req["recent_views"], best, unavailable),
             "model_version": "baseline"} for req in requests]


def recommend(recent_views: list[Record], best: list[str], unavailable: set[str] = frozenset()) -> list[str]:
    """10 product IDs for one request: the part teams replace. Here: the first 10 best sellers in stock."""
    return [product for product in best if product not in unavailable][:10]


def push(answers: list[Record]) -> None:
    """Batch insert into team_NN.submissions."""
    http.post(f"{API}/v1/tables/submissions", params={"database": TEAM}, json=answers, timeout=10).raise_for_status()
    print(f"answered {len(answers)}")


def main() -> None:
    best: list[str] = []
    seen = set[str]()
    unavailable: set[str] = set()
    stock_checked = 0.0
    while True:
        try:
            if not best:
                best = best_sellers()
            if time.time() - stock_checked >= 1:  # stock changes every few minutes: once a second is plenty
                stock_checked = time.time()
                try:
                    unavailable = out_of_stock()
                except Exception as e:  # keep answering with the last known stock
                    print(f"stock check failed: {e}")
            answers = predict(pull(seen), best, unavailable)
            if answers:
                push(answers)
        except Exception as e:  # keep running: shoppers keep arriving while you sleep
            print(f"error: {e}")
            time.sleep(2)
        time.sleep(0.3)


if __name__ == "__main__":
    main()
