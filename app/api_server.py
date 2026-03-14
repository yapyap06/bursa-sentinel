"""
BursaSentinel — Flask API Server (Phase 5)
==========================================
Exposes the SequentialAgent swarm over HTTP so the dashboard can call it live.

Endpoints:
  GET  /api/health               — server + swarm status
  GET  /api/analyze?ticker=X     — run full swarm, return JSON report (cached 15 min)
  GET  /api/batch?tickers=A,B,C  — run batch + WatchlistAgent
  GET  /api/stream/<ticker>      — Server-Sent Events: live pipeline stage updates
  DELETE /api/cache              — clear the result cache

Run:
  python -m app.api_server
  # or
  python app/api_server.py
"""

import json
import os
import sys
import time
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from queue import Empty, Queue
from typing import Any

# ── make sure project root is importable ─────────────────────────────────── #
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from agents.swarm import BursaSentinelSwarm
from agents._logger import get_swarm_logger

app = Flask(__name__)
CORS(app)

log = get_swarm_logger("APIServer")
_START_TIME = time.time()

# ── Lazy-init swarm (avoid Gemini import at module level failing) ─────────── #
_swarm: BursaSentinelSwarm | None = None
_swarm_lock = threading.Lock()

def get_swarm() -> BursaSentinelSwarm:
    global _swarm
    if _swarm is None:
        with _swarm_lock:
            if _swarm is None:
                _swarm = BursaSentinelSwarm()
    return _swarm

# ── Thread-safe in-memory cache ───────────────────────────────────────────── #
_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "900"))   # default 15 min

def cache_get(key: str) -> dict | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and (time.time() - entry["_cached_at"]) < CACHE_TTL:
            return entry
        return None

def cache_set(key: str, value: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = {**value, "_cached_at": time.time()}

def cache_clear() -> int:
    with _CACHE_LOCK:
        n = len(_CACHE)
        _CACHE.clear()
        return n

# ── SSE event queues (one per active stream) ──────────────────────────────── #
_SSE_QUEUES: dict[str, list[Queue]] = {}
_SSE_LOCK = threading.Lock()

def _sse_publish(ticker: str, event: str, data: dict) -> None:
    """Push an SSE event to all active streams for this ticker."""
    message = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    with _SSE_LOCK:
        for q in _SSE_QUEUES.get(ticker.upper(), []):
            q.put(message)

def _sse_register(ticker: str) -> Queue:
    q: Queue = Queue(maxsize=50)
    with _SSE_LOCK:
        _SSE_QUEUES.setdefault(ticker.upper(), []).append(q)
    return q

def _sse_unregister(ticker: str, q: Queue) -> None:
    with _SSE_LOCK:
        try:
            _SSE_QUEUES.get(ticker.upper(), []).remove(q)
        except ValueError:
            pass

# ── Swarm runner that emits SSE events ───────────────────────────────────── #

def _run_swarm_with_sse(ticker: str) -> dict:
    """
    Run the swarm pipeline, publishing SSE stage events in real time.
    Returns the final report dict.
    """
    ticker = ticker.upper()
    swarm = get_swarm()

    _sse_publish(ticker, "stage", {
        "stage": 1, "agent": "InfiltratorAgent",
        "status": "RUNNING", "message": f"Querying BursaScraperTool + NewsScraperTool for {ticker}…"
    })
    t0 = time.time()
    infiltrator_output = swarm.infiltrator.run(ticker)
    s1_ms = int((time.time() - t0) * 1000)

    _sse_publish(ticker, "stage", {
        "stage": 1, "agent": "InfiltratorAgent",
        "status": "DONE", "elapsed_ms": s1_ms,
        "data_gaps": infiltrator_output.get("data_gaps", []),
    })
    _sse_publish(ticker, "stage", {
        "stage": 2, "agent": "StrategistAgent",
        "status": "RUNNING", "message": "Applying thresholds + Agentic Recovery…"
    })

    t1 = time.time()
    strategist_output = swarm.strategist.run(infiltrator_output)
    s2_ms = int((time.time() - t1) * 1000)

    _sse_publish(ticker, "stage", {
        "stage": 2, "agent": "StrategistAgent",
        "status": "DONE", "elapsed_ms": s2_ms,
        "recommendation": strategist_output.get("recommendation"),
    })

    total_ms = int((time.time() - t0) * 1000)
    report = BursaSentinelSwarm._assemble_report(
        ticker, infiltrator_output, strategist_output,
        s1_ms=s1_ms, s2_ms=s2_ms, total_ms=total_ms
    )

    _sse_publish(ticker, "complete", {
        "stage": 3, "agent": "Report",
        "status": "DONE", "elapsed_ms": total_ms,
        "recommendation": report["final_recommendation"]["recommendation"],
        "confidence": report["final_recommendation"]["confidence"],
    })
    return report


# ── Routes ────────────────────────────────────────────────────────────────── #

@app.route("/api/health")
def api_health():
    api_key_set = bool(os.getenv("GOOGLE_API_KEY"))
    return jsonify({
        "status": "ok",
        "version": "5.0.0",
        "uptime_s": round(time.time() - _START_TIME, 1),
        "api_key_configured": api_key_set,
        "cache_entries": len(_CACHE),
        "cache_ttl_s": CACHE_TTL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/analyze")
def api_analyze():
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "Missing ?ticker= parameter"}), 400

    force = request.args.get("force", "false").lower() == "true"

    # Serve from cache unless forced
    if not force:
        cached = cache_get(ticker)
        if cached:
            cached["_from_cache"] = True
            return jsonify(cached)

    try:
        report = _run_swarm_with_sse(ticker)
        cache_set(ticker, report)
        report["_from_cache"] = False
        return jsonify(report)
    except Exception as e:
        log.error("analyze_error", extra={"ticker": ticker, "error": str(e)})
        return jsonify({"error": str(e), "ticker": ticker}), 500


@app.route("/api/batch")
def api_batch():
    raw = request.args.get("tickers", "")
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    if not tickers:
        return jsonify({"error": "Missing ?tickers= parameter (comma-separated)"}), 400
    if len(tickers) > 8:
        return jsonify({"error": "Maximum 8 tickers per batch"}), 400

    force = request.args.get("force", "false").lower() == "true"

    try:
        swarm = get_swarm()
        individual = []
        for tk in tickers:
            cached = None if force else cache_get(tk)
            if cached:
                individual.append(cached)
            else:
                report = _run_swarm_with_sse(tk)
                cache_set(tk, report)
                individual.append(report)

        strategist_outputs = [r["strategist_analysis"] for r in individual]
        watchlist = swarm.watchlist_agent.run(strategist_outputs)

        return jsonify({
            "mission": "BursaSentinel Batch Analysis",
            "tickers": tickers,
            "individual_reports": individual,
            "watchlist_analysis": watchlist,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        log.error("batch_error", extra={"tickers": tickers, "error": str(e)})
        return jsonify({"error": str(e)}), 500


@app.route("/api/stream/<ticker>")
def api_stream(ticker: str):
    """
    Server-Sent Events endpoint.
    The client connects BEFORE clicking Run — then triggers /api/analyze in parallel.
    Events: stage, complete, error
    """
    ticker = ticker.upper()
    q = _sse_register(ticker)

    def generate():
        # Send connection confirmation
        yield f"event: connected\ndata: {json.dumps({'ticker': ticker})}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                    if '"complete"' in msg or '"error"' in msg:
                        break
                except Empty:
                    # Keepalive ping
                    yield ": keepalive\n\n"
        finally:
            _sse_unregister(ticker, q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/cache", methods=["DELETE"])
def api_cache_clear():
    n = cache_clear()
    return jsonify({"cleared": n, "message": f"Removed {n} cached report(s)"})


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error", "detail": str(e)}), 500


# ── Main ──────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BursaSentinel API Server v5")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    key_preview = os.getenv("GOOGLE_API_KEY", "")[:8] or "(not set)"
    print(f"[APIServer] 🛰️  BursaSentinel API v5.0.0")
    print(f"[APIServer] GOOGLE_API_KEY: {key_preview}…")
    print(f"[APIServer] http://{args.host}:{args.port}/api/health")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
