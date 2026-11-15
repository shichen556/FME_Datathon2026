# Real-Time Recommender · Team 34 · RawTree Challenge (Datathon FME 2026)

**Team:** Cristian · Rubén · Shichen &nbsp;|&nbsp; **Final system:** `v3-Shichen` (`starter/recommender_v2.py`)

The original challenge statement is kept in [`CHALLENGE.md`](CHALLENGE.md). This README explains **how** we built the system and **why** we made each decision, including what we did *not* manage to validate.

---

## 1. What it does (one paragraph)

For every shopper request, the system answers within the 3-second limit with an ordered list of 10 products. It puts first what the shopper already looked at in this session, then what other shoppers bought after looking at the same products, then best sellers of the same subcategories, and finally what sells best right now. It never shows out-of-stock, inactive, or recently bought products. Everything heavy is computed in SQL inside RawTree and refreshed in the background, so answering a request is a pure in-memory lookup (< 1 ms).

## 2. Why this design: what the data told us

The ranking structure comes from analysing `shop.history_sessions` (≈2M impressions) and `shop.history_events`. These figures are the ones quoted in the module docstring of `starter/recommender_v2.py`:

| Finding | Consequence in the model |
|---|---|
| A product the shopper **viewed earlier in the session**, shown in slot 1, is bought ~17× more than any other product in slot 1 (6.3 % vs 0.37 %) | Phase 1 of every list: the viewed products |
| Products **bought in sessions where a viewed product was viewed** are bought ~7× more than the rest | Phase 2: co-purchase candidates (view → purchase) |
| **Position matters**: slot 1 gets ~2× the purchases of slot 2 and ~9× those of slot 10 | Most likely product goes first; order is deliberate |
| The old system was "best sellers + a bit of randomness", so the log is biased toward popular items | We do not trust raw hit-rate on that log (see §5) |

The ranking pipeline, in order, until 10 products are filled:

1. **Viewed products** of the session (most viewed first, then most recent), minus anything already bought.
2. **Co-purchases** of the viewed products, weighted by an exponential decay of 0.8 per view age.
3. **Best sellers of the viewed subcategories** (max 5 per subcategory).
4. **Global best sellers** as final filler (this is what shoppers with no views receive), capped at 5 per subcategory for diversity.

## 3. How it works (architecture)

```
 shop.requests ──▶ main loop (poll → recommend() in RAM → batch push) ──▶ team_34.submissions
                          ▲ reads the current Model
                          │
          Refresher thread (background)
            • every ~2 s : stock (out_of_stock / back_in_stock) + recent buyers
            • every 10 min: full rebuild of co-purchases, popularity, catalogue
          all heavy work is SQL executed inside RawTree
```

- **No ML model is trained.** The "training" is SQL aggregation in RawTree: co-occurrence counts of view → purchase per session, and popularity scores. This is deliberate: it is fast, explainable, and robust under a 3-second deadline.
- **Popularity with recency and live signal:** all-time purchases + 5× last 7 days + 20× live `shop.events` + 40× last 3 hours, so the ranking reacts to trends during the event.
- **Validity filters:** out-of-stock (latest stock change per product), inactive (`is_active`, with `catalog_updates` applied), and products the user bought in the last 6 hours (store events + our own feedback). One invalid product invalidates the whole answer, so these filters protect reliability.
- **Resilience:** the answering loop never waits for the database refresh; if a refresh fails, the last good model is kept and the error is logged.

## 4. Learning from the stream: what is and is not live

| Signal | Used live? |
|---|---|
| `shop.events` purchases (popularity and co-purchase) | Yes, refreshed every 10 min; popularity weights live events 20×/40× |
| Stock changes (`catalog_updates`) | Yes, every ~2 s |
| Recent purchases per user (store + our `team_34.feedback`) | Yes, every ~2 s, used only to avoid re-recommending |
| Clicks and purchases in our own feedback as a learning signal | **No** (only used to exclude repeat purchases) |
| Price changes, device, region, page | **No** |
| New products (cold start) | **No**: they enter with score 0 |

## 5. How we validated it (honest account)

- **Offline:** `starter/offline_eval.ipynb` was run on a 7-day hold-out of `history_sessions` for two policies: `baseline` and `coview`. Saved results:

  | Policy | hit-rate@10 | SNIPS CTR slot 1 | slot-1 matches |
  |---|---|---|---|
  | baseline (best sellers) | 0.380 | 0.047 | 3,915 |
  | coview | 0.234 | 0.011 | 5,499 |

  The co-view policy scores **below** the baseline on both metrics. We did not manage to interpret these metrics well enough to use them to tune the final model. One known caveat: the log was produced by a popularity-based system, so hit-rate favours popular products by construction. **The final policy (`v3-Shichen`) was never added to the notebook's `POLICIES`, so it has no offline score.**
- **Weights are hand-set** (0.8 decay, 5×/20×/40×, cap of 5). They are heuristics inspired by the data findings in §2, not fitted values.
- **Unit tests:** `tests/test_recommender_v2.py` has 50 tests. In our run with no network, 37 passed and the suite then **hung** on the first `Refresher` test, because `Refresher.run()` is an infinite loop and the test treats it as a single iteration. The remaining tests did not complete. This is a bug in the tests, not in the runtime loop.
- **Live:** in the final round window we looked at (`team_34.feedback`, 10:34–10:49 UTC), 2,698 of 2,700 requests were served by our system (99.93 %) and the p95 latency was 2.0–2.3 s per minute, under the 3 s limit but without a lot of margin.
- **Conversion and revenue per request** of the final round: *TODO(team): fill in from `team_34.feedback` using the query in §8.*

## 6. How we worked: team, branches and AI agents

Each person worked on their own branch. Versions follow the naming `vX_NAME` (X = version number, NAME = who pushed it), and each one reports it in `model_version`, so `team_34.submissions` shows which version answered.

| Person | Branch | What they did | AI tools used |
|---|---|---|---|
| **Shichen** | `infraestructure` | Wrote the final system (`recommender_v2.py`): phased ranking, filters, background `Refresher`, pytest suite, merge and repo upkeep | Claude Opus 5.5 (first version of the code), qwen3.6 (incremental improvements) |
| **Cristian** | `data` | Data exploration and tooling (`run_sql.py`, `carga.sql`, live diagnostic queries); an alternative recommender (`v3 - Cristian`) with live carts, user profile and price affinity, region/device price model and text-based cold start | Gemini 4 HydroGen (initial approach and explaining the project's concepts), Claude Sonnet 5.5 (code and incremental improvements) |
| **Rubén** | `algorithm` | `v2-ruben`: hybrid scoring on category/subcategory/brand affinity, per-category cap, faster polling (0.1 s) and batched pushes | ChatGPT 6 (code) |

**What humans decided vs what the agents wrote:** the agents produced most of the code; the team decided the approach, ran every query against RawTree, debugged real errors from our own runs (for example Dynamic-type casts, a SQL aggregate-alias error, and a stock-detection edge case), and chose the final version.

### Why `v3-Shichen` and not the others

| Version | Strengths | Weaknesses |
|---|---|---|
| `v3-Shichen` (final) | Structure derived from the data (retarget viewed products, co-purchase), simple, tested, stable live | Heuristic weights, no cold start, ignores device/region/price |
| `v3 - Cristian` | Richest signal set: live carts, user profile and price, price model by region and device, discount boost, text-based cold start | Many hand-set weights with no tests and no offline evaluation; we could not show it beating the simpler version |
| `v2-ruben` | Clean hybrid score, good batching | Excludes already-viewed products, which contradicts the 17× finding; no co-purchases, no live events, no `catalog_updates` |

*TODO(team): confirm or adjust this rationale before the demo.*

## 7. Known limitations and what we would do next

1. **Validate offline:** add the final policy to `POLICIES` in `offline_eval.ipynb` and compare with IPS/SNIPS; then **fit** the weights instead of hand-setting them.
2. **Cold start:** products added during the event get no score today. Use text similarity or embeddings on `description` (Cristian's branch has a first version).
3. **Context:** use `device`, `region`, `page` and price affinity (the history shows large price differences by region and device).
4. **Learn from our own feedback** (clicks and purchases), and add exploration (bandit) for rarely shown products.
5. **Longer purchase memory:** we only exclude purchases from the last 6 h, not the 60-day history.
6. **Robustness:** swap the whole `Model` atomically in the `Refresher` instead of reassigning fields one by one (a request could briefly see a mix of old and new fields); stock refresh is a few seconds, so a product going out of stock in that gap would invalidate an answer; run under `systemd`/`tmux`.
7. **Latency margin:** p95 ≈ 2 s is high compared with the ≈1 s the starter gets; profile the main loop and the polling interval.
8. **Fix the Refresher tests** (add a `run_once()` or a stop flag).

## 8. Run it

```bash
cp .env.example .env            # fill TEAM_ID and RAWTREE_API_KEY (never commit .env)
pip install -r starter/requirements.txt pytest
python starter/recommender_v2.py            # the live system (run from the repo root)
python -m pytest tests/test_recommender_v2.py -v   # see §5 about the Refresher tests
jupyter notebook starter/offline_eval.ipynb        # offline evaluation
```

Conversion and revenue per request by version (for the tie-breaker), from `team_34.feedback` joined with `team_34.submissions`:

```sql
SELECT s.model_version::String AS model_version,
       count() AS requests,
       100 * countIf(f.purchased::String != '') / count() AS conversion_pct,
       sum(f.revenue_eur::Float64) / count() AS revenue_per_request
FROM team_34.feedback AS f
INNER JOIN team_34.submissions AS s ON f.request_id::String = s.request_id::String
WHERE f.request_id != '__init__' AND f.served_by::String = 'team'
GROUP BY model_version
```

(Only meaningful if a single version was answering during the period; two versions answering the same request mix the feedback.)

## 9. Repository map

| Path | Content |
|---|---|
| `starter/recommender_v2.py` | **Final system** (`MODEL_VERSION = "v3-Shichen"`) |
| `starter/recommender.py` | Organisers' baseline (also the fallback) |
| `starter/offline_eval.ipynb` | Offline evaluation (baseline vs coview results saved) |
| `starter/queries.sql` | SQL examples (note: `team_34` is hard-coded; use `team_NN` as the template) |
| `tests/` | pytest suite |
| `checklist_log_versiones.md`, `roadmap.md` | Per-version log and team checklist |
| `request.py` | Connectivity check for an LLM gateway used while developing; **not part of the recommender** |