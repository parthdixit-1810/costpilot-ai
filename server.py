"""CostPilot AI — FastAPI-compatible server (stdlib fallback included).

Run with Python stdlib:
    python server.py

Set ANTHROPIC_API_KEY for live Claude AI planning.
Either export it in your shell, or create a .env file:
    echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.resolve()
DB_PATH = ROOT / "costpilot.db"

# ── .ENV AUTO-LOAD ────────────────────────────────────────────────────────────

def _load_env() -> None:
    """Load key=value pairs from .env without requiring python-dotenv."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = val

_load_env()

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ── SQLITE DATABASE ───────────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist."""
    with sqlite3.connect(DB_PATH) as cx:
        cx.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                budget     INTEGER NOT NULL,
                engine     TEXT,
                type       TEXT,
                goal       TEXT,
                created_at INTEGER NOT NULL,
                payload    TEXT
            )
        """)
        cx.execute("CREATE INDEX IF NOT EXISTS idx_plans_created ON plans(created_at DESC)")
        cx.commit()

@contextmanager
def get_db():
    cx = sqlite3.connect(DB_PATH)
    cx.row_factory = sqlite3.Row
    try:
        yield cx
        cx.commit()
    finally:
        cx.close()

def db_push_plan(entry: dict[str, Any], payload: dict[str, Any] | None = None) -> None:
    global _history_cache
    _history_cache = (0.0, [])  # invalidate cache
    with get_db() as cx:
        cx.execute(
            "INSERT INTO plans (title, budget, engine, type, goal, created_at, payload) VALUES (?,?,?,?,?,?,?)",
            (
                entry.get("title", ""),
                int(entry.get("budget", 0)),
                entry.get("engine", ""),
                entry.get("type", ""),
                entry.get("goal", ""),
                int(entry.get("created_at", time.time())),
                json.dumps(payload) if payload else None,
            ),
        )

_history_cache: tuple[float, list] = (0.0, [])
_HISTORY_TTL = 10  # seconds

def db_load_history(limit: int = 12) -> list[dict[str, Any]]:
    global _history_cache
    now = time.time()
    if now - _history_cache[0] < _HISTORY_TTL and _history_cache[1]:
        return _history_cache[1][:limit]
    with get_db() as cx:
        rows = cx.execute(
            "SELECT title, budget, engine, type, goal, created_at FROM plans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = [dict(r) for r in rows]
    _history_cache = (now, result)
    return result[:limit]

# ── TYPE CONFIG ──────────────────────────────────────────────────────────────

TYPE_CONFIG: dict[str, dict[str, Any]] = {
    "travel": {
        "label": "Travel plan",
        "buckets": ["Transit", "Stay", "Food", "Activities", "Local transport"],
        "weights": [0.34, 0.27, 0.16, 0.15, 0.08],
    },
    "gadget": {
        "label": "Gadget purchase plan",
        "buckets": ["Device", "Warranty", "Accessories", "Discounts", "Resale buffer"],
        "weights": [0.78, 0.08, 0.06, 0.04, 0.04],
    },
    "relocation": {
        "label": "Relocation plan",
        "buckets": ["Deposit", "Moving", "Furniture", "Commute", "Setup"],
        "weights": [0.46, 0.16, 0.18, 0.09, 0.11],
    },
    "event": {
        "label": "Event plan",
        "buckets": ["Venue", "Catering", "Decor", "Photo", "Logistics"],
        "weights": [0.24, 0.42, 0.14, 0.09, 0.11],
    },
}

VARIANTS = [
    {"id": "cheapest", "name": "Cheapest",   "badge": "Lowest cash out", "multiplier": 0.82, "speed": 68,  "quality": 74,
     "explanation": "Uses flexible timing, modest choices, and the least expensive viable combinations across all cost buckets."},
    {"id": "fastest",  "name": "Fastest",    "badge": "Time saver",      "multiplier": 1.13, "speed": 94,  "quality": 82,
     "explanation": "Spends selectively to reduce waiting, coordination effort, and avoidable delays throughout the plan."},
    {"id": "value",    "name": "Best value", "badge": "Recommended",     "multiplier": 0.96, "speed": 84,  "quality": 91,
     "explanation": "Balances the full solution by avoiding cheap components that create downstream cost and friction."},
    {"id": "premium",  "name": "Premium",    "badge": "Comfort first",   "multiplier": 1.27, "speed": 88,  "quality": 97,
     "explanation": "Prioritises reliability, comfort, warranty, support, and lower execution risk throughout the plan."},
]

# ── HELPERS ──────────────────────────────────────────────────────────────────

def money(v: float) -> str:
    return f"₹{round(v):,}"

def read_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", 0))
    return json.loads(handler.rfile.read(length).decode()) if length else {}

def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    t = raw.get("type") if raw.get("type") in TYPE_CONFIG else "travel"
    # Gadget purchases don't have a meaningful duration or origin city
    is_gadget = (t == "gadget")
    return {
        "goal":       str(raw.get("goal") or "").strip()[:1200],
        "type":       t,
        "budget":     max(1, int(raw.get("budget") or 25000)),
        "duration":   1 if is_gadget else max(1, int(raw.get("duration") or 1)),
        "origin":     "" if is_gadget else str(raw.get("origin") or "Delhi")[:80],
        "priority":   str(raw.get("priority") or "balanced"),
        "options":    raw.get("options") if isinstance(raw.get("options"), dict) else {},
        "travellers": max(1, int(raw.get("travellers") or 1)),
        "transport":  str(raw.get("transport") or "recommend"),
        "departure_date": str(raw.get("departure_date") or ""),
        "date_flex":  str(raw.get("date_flex") or "fixed"),
        "retry_only": bool(raw.get("retry_only", False)),
    }

def priority_adj(priority: str, variant_id: str) -> float:
    if priority == "cheap":   return -0.05 if variant_id == "cheapest" else 0.02
    if priority == "fast":    return -0.03 if variant_id == "fastest"  else 0.02
    if priority == "quality": return  0.03 if variant_id in {"value", "premium"} else -0.01
    return 0.0

def cost_breakdown(total: float, goal_type: str, live_prices: dict | None = None) -> list[dict[str, Any]]:
    cfg = TYPE_CONFIG[goal_type]
    rows = []
    for l, w in zip(cfg["buckets"], cfg["weights"], strict=True):
        row: dict[str, Any] = {"label": l, "amount": round(total * w)}
        if live_prices and l in live_prices:
            lp = live_prices[l]
            if isinstance(lp, dict) and lp.get("typical", 0) > 0:
                row["live_low"]     = int(lp.get("low", 0))
                row["live_high"]    = int(lp.get("high", 0))
                row["live_typical"] = int(lp["typical"])
                row["live_source"]  = str(lp.get("source", "Web"))[:60]
        rows.append(row)
    # For gadget: attach models array to the Device bucket row
    if goal_type == "gadget" and live_prices and live_prices.get("models"):
        for row in rows:
            if row["label"].lower() == "device":
                row["live_models"] = live_prices["models"]
                # Also set live range from top-level
                if live_prices.get("typical", 0) > 0 and not row.get("live_typical"):
                    row["live_low"]     = int(live_prices.get("low", 0))
                    row["live_high"]    = int(live_prices.get("high", 0))
                    row["live_typical"] = int(live_prices["typical"])
                    row["live_source"]  = str(live_prices.get("source", "Web"))[:60]
                break
    return rows

# ── DETERMINISTIC OPTIMIZER ──────────────────────────────────────────────────

def extract_title(goal: str, goal_type: str, origin: str) -> str:
    """Pull a meaningful destination/subject from the goal text."""
    import re
    if not goal:
        return {"travel": f"Trip from {origin}", "gadget": "Gadget purchase", "relocation": f"Relocation from {origin}", "event": "Event plan"}.get(goal_type, "Plan")

    if goal_type == "gadget":
        # Try to extract brand+model (e.g. "iPhone 15 Pro", "MacBook Air M2", "Samsung S24")
        gm = re.search(r'\b(iPhone\s*\d+\w*(?:\s+\w+)?|MacBook\s+\w+(?:\s+\w+)?|Samsung\s+\w+\d+\w*|OnePlus\s+\d+\w*|Pixel\s+\d+\w*|iPad\s+\w*|Dell\s+\w+|HP\s+\w+|Sony\s+\w+)', goal, re.I)
        if gm:
            return f"{gm.group(1).strip()} purchase"
        gm2 = re.search(r'\b(laptop|phone|tablet|camera|smartwatch|headphone|speaker|TV|monitor|keyboard)\b', goal, re.I)
        if gm2:
            return f"{gm2.group(1).capitalize()} purchase"
        return "Gadget purchase"

    if goal_type == "relocation":
        dest = re.search(r'\bto\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b', goal)
        if dest and dest.group(1).lower() not in (origin.lower(), "a", "the", "my"):
            return f"Relocation to {dest.group(1)}"
        return f"Relocation from {origin}"

    if goal_type == "event":
        for pat in [r'\b(wedding|birthday|anniversary|conference|concert|festival|farewell|reunion)\b']:
            em = re.search(pat, goal, re.I)
            if em:
                dest = re.search(r'\bin\s+([A-Z][a-zA-Z]+)\b', goal)
                loc = f" in {dest.group(1)}" if dest else ""
                return f"{em.group(1).capitalize()}{loc}"
        return "Event plan"

    # travel
    patterns = [
        r'\bto\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b',
        r'\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b',
        r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+trip\b',
        r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+tour\b',
        r'\bvisit\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b',
    ]
    for pat in patterns:
        m = re.search(pat, goal)
        if m and m.group(1).lower() not in (origin.lower(), "a", "the", "my"):
            return f"{m.group(1)} trip from {origin}"
    return f"Trip from {origin}"

def build_plans(p: dict[str, Any], llm: dict[str, Any] | None = None, live_prices: dict | None = None) -> list[dict[str, Any]]:
    cfg = TYPE_CONFIG[p["type"]]
    budget = p["budget"]
    # Cap duration factor so cheapest variant always stays within budget
    raw_df = max(0.72, p["duration"] / 4) if p["type"] == "travel" else 1.0
    df = min(raw_df, 1 / 0.84)
    plans: list[dict[str, Any]] = []

    for v in VARIANTS:
        adj   = v["multiplier"] + priority_adj(p["priority"], v["id"])
        total = round(budget * adj * df)
        delta = budget - total
        fit   = round((v["quality"] + v["speed"] + (96 if delta >= 0 else 70)) / 3)
        fit   = max(55, min(98, fit))

        # Try to get per-variant enrichment from LLM
        llm_plan = {}
        if llm and isinstance(llm.get("plans"), dict):
            llm_plan = llm["plans"].get(v["id"]) or {}

        plans.append({
            "id":               v["id"],
            "name":             v["name"],
            "badge":            v["badge"],
            "total_cost":       total,
            "budget_delta":     delta,
            "budget_delta_label": f"{money(abs(delta))} {'under' if delta >= 0 else 'over'} budget",
            "fit_score":        fit,
            "time_label": (
                f"{max(1, round(p['duration'] * (100 / v['speed'])))} day impact"
                if p["type"] == "travel"
                else f"{max(1, round(100 / v['speed'] * 8))} effort score"
            ),
            "quality_score": v["quality"],
            "explanation":   llm_plan.get("explanation") or v["explanation"],
            "cost_breakdown": cost_breakdown(total, p["type"], live_prices),
            "tradeoffs": llm_plan.get("tradeoffs") or [
                "Lower cost increases flexibility and coordination requirements.",
                "Higher fit score means fewer weak links in the complete solution.",
                "Best route depends on whether cash, time, or reliability matters most.",
            ],
            "savings": llm_plan.get("savings") or [
                f"Shift one major bucket by 10–15% to target {money(max(500, budget * 0.06))} in savings.",
                "Use price alerts to wait for a better booking or quote window.",
                "Bundle adjacent vendor decisions before negotiating.",
            ],
        })

    return plans

def full_result(p: dict[str, Any], llm: dict[str, Any] | None = None, live_prices: dict | None = None, travel_packages: list | None = None) -> dict[str, Any]:
    cfg   = TYPE_CONFIG[p["type"]]
    plans = build_plans(p, llm, live_prices)

    llm_summary = {}
    if llm:
        raw = llm.get("summary") or {}
        llm_summary = raw if isinstance(raw, dict) else {"headline": str(raw)}

    title = extract_title(p["goal"], p["type"], p["origin"])
    cheap = min(plans, key=lambda x: x["total_cost"])
    best_saving = max(0, p["budget"] - cheap["total_cost"])
    priority_map = {"cheap": "cheapest", "fast": "fastest", "quality": "premium"}
    rec_id   = priority_map.get(p["priority"], "value")
    rec_plan = next((x for x in plans if x["id"] == rec_id), plans[0])
    headline = (
        llm_summary.get("headline") or
        (f"{rec_plan['name']} recommended — save up to {money(best_saving)} vs premium." if best_saving > 0
         else f"{rec_plan['name']} is the strongest fit for your {money(p['budget'])} budget.")
    )

    result: dict[str, Any] = {
        "id":           str(uuid.uuid4()),
        "title":        title,
        "engine_label": (
            "Gemini AI + optimizer" if llm and llm.get("mode") in ("claude", "gemini")
            else "Local optimizer"
        ),
        "constraints": {
            "goal":     p["goal"],
            "type":     p["type"],
            "budget":   p["budget"],
            "duration": p["duration"],
            "priority": p["priority"],
        },
        "summary": {
            "headline":    headline,
            "best_saving": best_saving,
            "decision":    llm_summary.get("decision") or rec_plan["name"],
        },
        "trace": [
            {"label": "Goal parsed into structured constraints", "status": "done"},
            {"label": "Research agent synthesized market assumptions", "status": "done"},
            {"label": "Cost model built solution buckets", "status": "done"},
            {"label": "Optimizer scored four routes", "status": "done"},
            {"label": "Explanation agent wrote rationale", "status": "done"},
        ],
        "plans":            plans,
        "knowledge_graph":  {"nodes": cfg["buckets"]},
        "llm_notes":        llm or {"mode": "mock", "reason": "No API key set (ANTHROPIC_API_KEY or GEMINI_API_KEY)"},
        "travel_packages":  travel_packages or [],
        "places_to_visit":  (llm or {}).get("places_to_visit") or [],
        "itinerary":        (llm or {}).get("itinerary") or [],
    }

    if not p.get("retry_only"):
        entry = {
            "title":      result["title"],
            "budget":     p["budget"],
            "engine":     result["engine_label"],
            "type":       p["type"],
            "goal":       p["goal"],
            "created_at": int(time.time()),
        }
        db_push_plan(entry, payload=result)
    result["history"] = db_load_history(12)
    return result

# ── SHARED PROMPT BUILDER ────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are CostPilot AI, an expert cost optimization engine for Indian consumers. "
    "Analyse the user's goal and return ONLY compact JSON with these exact keys:\n"
    "{\n"
    '  "summary": {"headline": string, "decision": string},\n'
    '  "assumptions": [string],\n'
    '  "risks": [string],\n'
    '  "places_to_visit": [{"name": string, "why": string, "tip": string}],\n'
    '  "itinerary": [{"day": number, "title": string, "activities": [string], "meals": string, "estimated_cost": number}],\n'
    '  "plans": {\n'
    '    "cheapest": {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]},\n'
    '    "fastest":  {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]},\n'
    '    "value":    {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]},\n'
    '    "premium":  {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]}\n'
    "  }\n"
    "}\n"
    "Be specific to the Indian market, destination, and budget. "
    "For places_to_visit: list 5-8 must-see spots at the destination with a short why and practical tip. "
    "For itinerary: provide a day-by-day plan matching the trip duration — each day has a title, 3-5 activities, meals suggestion, and estimated daily spend in INR. "
    "If travel dates are provided, use actual calendar dates for each itinerary day. "
    "If date_flex is not fixed, note the best date window for cheaper prices. "
    "If transport_mode is 'recommend best option', compare flight/train/bus/cab costs and clearly state which is cheapest/fastest/best-value for the route. "
    "If travellers > 1, scale transit costs accordingly and note per-person vs total. "
    "Keep each string under 120 characters. No markdown, no extra keys."
)

def _user_msg(p: dict[str, Any]) -> str:
    msg: dict[str, Any] = {
        "goal":     p["goal"],
        "type":     p["type"],
        "budget":   f"₹{p['budget']:,}",
        "duration": p["duration"],
        "origin":   p["origin"],
        "priority": p["priority"],
        "options":  p["options"],
    }
    if p.get("travellers", 1) > 1:
        msg["travellers"] = p["travellers"]
    if p.get("transport") and p["transport"] != "recommend":
        msg["transport_mode"] = p["transport"]
    elif p.get("transport") == "recommend":
        msg["transport_mode"] = "recommend best option among flight/train/bus/cab and explain why"
    if p.get("departure_date"):
        msg["departure_date"] = p["departure_date"]
    if p.get("date_flex") and p["date_flex"] != "fixed":
        msg["date_flexibility"] = p["date_flex"]
    return json.dumps(msg, ensure_ascii=False)

def _parse_llm_text(text: str) -> dict[str, Any]:
    text = text.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    text = text.rstrip("`").strip()
    return json.loads(text)

# ── GEMINI AI CALL (stdlib only — no extra packages) ─────────────────────────

GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

def _extract_destination(goal: str) -> str:
    """Pull destination city from free-text goal."""
    import re
    for pat in [r'\bto\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b',
                r'\bin\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\b',
                r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+trip\b']:
        m = re.search(pat, goal)
        if m:
            return m.group(1).strip()
    return ""

def _gemini_raw_text(prompt: str, max_tokens: int = 1000) -> str | None:
    """Call Gemini with Google Search grounding; return raw text or None."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    url  = GEMINI_API_URL.format(model=GEMINI_MODEL, key=api_key)
    body = json.dumps({
        "tools": [{"google_search": {}}],
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens, "thinkingConfig": {"thinkingBudget": 0}},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return next((p.get("text","") for p in parts if p.get("text")), "").strip()
    except Exception as e:
        print(f"[gemini_raw] error: {e}", flush=True)
        return None

PACKAGES_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "destination": {"type": "string"},
        "origin": {"type": "string"},
        "nights": {"type": "integer"},
        "per_day_extras": {
            "type": "object",
            "properties": {
                "food": {"type": "integer"},
                "local_transport": {"type": "integer"},
                "activities": {"type": "integer"},
            },
            "required": ["food", "local_transport", "activities"],
        },
        "packages": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "tier": {"type": "string", "enum": ["Budget", "Comfort", "Premium"]},
                    "transport_mode": {"type": "string"},
                    "transport_name": {"type": "string"},
                    "transport_detail": {"type": "string"},
                    "flight_price": {"type": "integer"},
                    "flight_source": {"type": "string"},
                    "flight_operator": {"type": "string"},
                    "hotels": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {
                                "hotel_name": {"type": "string"},
                                "hotel_address": {"type": "string"},
                                "hotel_per_night": {"type": "integer"},
                                "hotel_source": {"type": "string"},
                                "hotel_rating": {"type": "string"},
                            },
                            "required": ["hotel_name", "hotel_address", "hotel_per_night", "hotel_source", "hotel_rating"],
                        },
                    },
                    "total": {"type": "integer"},
                },
                "required": ["tier", "transport_mode", "transport_name", "transport_detail",
                             "flight_price", "flight_source", "flight_operator", "hotels", "total"],
            },
        },
    },
    "required": ["destination", "origin", "nights", "per_day_extras", "packages"],
}

# Reusable bucket schema (low/high/typical/source) for non-travel types
def _bucket_prop():
    return {"type": "object", "properties": {
        "low": {"type": "integer"}, "high": {"type": "integer"},
        "typical": {"type": "integer"}, "source": {"type": "string"},
    }, "required": ["low", "high", "typical", "source"]}

_MODEL_ITEM = {
    "type": "object",
    "properties": {
        "name":        {"type": "string"},   # e.g. "Lenovo IdeaPad Slim 5"
        "variant":     {"type": "string"},   # e.g. "Intel i5-12th Gen, 16GB RAM, 512GB SSD"
        "tag":         {"type": "string"},   # e.g. "Best value", "Premium pick", "Budget option"
        "image_url":   {"type": "string"},   # CDN image URL
        "prices": {"type": "object", "properties": {
            "Flipkart":        {"type": "integer"},
            "Amazon":          {"type": "integer"},
            "Croma":           {"type": "integer"},
            "Reliance Digital":{"type": "integer"},
            "TataCliq":        {"type": "integer"},
        }, "required": ["Flipkart", "Amazon", "Croma", "Reliance Digital", "TataCliq"]},
        "lowest_site": {"type": "string"},   # site with lowest price
        "lowest_url":  {"type": "string"},   # direct product URL on lowest site
        "key_specs":   {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6},
        "pros":        {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
        "cons":        {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        "card_offers": {
            "type": "array",
            "items": {"type": "object", "properties": {
                "bank": {"type": "string"}, "card": {"type": "string"},
                "offer": {"type": "string"}, "max_discount": {"type": "integer"},
                "site": {"type": "string"},
            }, "required": ["bank", "card", "offer", "max_discount", "site"]},
        },
    },
    "required": ["name", "variant", "tag", "image_url", "prices", "lowest_site", "lowest_url", "key_specs", "pros", "cons"],
}

GADGET_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "models": {
            "type": "array",
            "items": _MODEL_ITEM,
            "minItems": 3, "maxItems": 5,
        },
        "Warranty":      _bucket_prop(),
        "Accessories":   _bucket_prop(),
        "Discounts":     _bucket_prop(),
        "Resale buffer": _bucket_prop(),
        "low":     {"type": "integer"},
        "high":    {"type": "integer"},
        "typical": {"type": "integer"},
        "source":  {"type": "string"},
    },
    "required": ["models", "Warranty", "Accessories", "Discounts", "Resale buffer", "low", "high", "typical", "source"],
}

RELOCATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "Deposit": _bucket_prop(),
        "Moving": _bucket_prop(),
        "Furniture": _bucket_prop(),
        "Commute": _bucket_prop(),
        "Setup": _bucket_prop(),
    },
    "required": ["Deposit", "Moving", "Furniture", "Commute", "Setup"],
}

EVENT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "Venue": _bucket_prop(),
        "Catering": _bucket_prop(),
        "Decor": _bucket_prop(),
        "Photo": _bucket_prop(),
        "Logistics": _bucket_prop(),
    },
    "required": ["Venue", "Catering", "Decor", "Photo", "Logistics"],
}

def _gemini_to_json(raw_text: str, json_schema: str, max_tokens: int = 800,
                    response_schema: dict | None = None) -> dict | None:
    """Call Gemini without tools to produce strict JSON.
    If response_schema is provided, uses Gemini's native responseSchema enforcement.
    If json_schema is a non-empty string, embeds it in the prompt (legacy path).
    Otherwise raw_text is the full prompt."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    url  = GEMINI_API_URL.format(model=GEMINI_MODEL, key=api_key)
    if response_schema:
        # Native schema enforcement — just send the prompt, schema is in generationConfig
        prompt = raw_text
    elif json_schema:
        prompt = (
            f"Extract the key facts from the research below and return ONLY valid JSON matching this schema exactly. "
            f"No prose, no markdown, no explanation — just the JSON object.\n\n"
            f"Schema:\n{json_schema}\n\n"
            f"Research:\n{raw_text}"
        )
    else:
        prompt = raw_text
    gen_config: dict = {
        "responseMimeType": "application/json",
        "temperature": 0.1,
        "maxOutputTokens": max_tokens,
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if response_schema:
        gen_config["responseSchema"] = response_schema
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = next((p.get("text","") for p in parts if p.get("text")), "").strip()
        for fence in ("```json", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
        return json.loads(text.rstrip("`").strip())
    except Exception as e:
        print(f"[gemini_to_json] error: {e}", flush=True)
        return None

CLARIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "corrected_goal": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "question": {"type": "string"},
                    "chips": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 8}
                },
                "required": ["key", "question", "chips"]
            },
            "minItems": 0,
            "maxItems": 4
        }
    },
    "required": ["ok"]
}

def _clarify_goal(goal: str, type_: str, budget: str) -> dict:
    """Ask Gemini if the goal is clear enough; return questions if not."""
    if not goal:
        q = {"key": "goal", "question": "What would you like to plan?",
             "chips": ["Goa trip for 4 days", "Buy a laptop under ₹70k", "Relocate to Bengaluru", "Birthday party for 30 guests"]}
        return {"ok": False, "questions": [q]}

    type_hints = {
        "travel":     "destination city/country, duration in days, and optionally origin city",
        "gadget":     "specific product name or category and budget range",
        "relocation": "destination city, reason for moving, and approximate timeline",
        "event":      "type of event (birthday/wedding/etc.), guest count, and budget",
    }
    hint = type_hints.get(type_, "enough detail to plan accurately")

    prompt = f"""You are a helpful assistant that checks if a user's goal is clear enough for planning.

Type: {type_}
User goal: "{goal}"
Budget: {budget if budget else "not specified"}

Required info for {type_}: {hint}

Your job:
1. Fix obvious spelling mistakes in the goal (e.g. "gao" → "Goa", "lapttop" → "laptop")
2. Identify what CRITICAL information is missing — only ask if truly needed
3. If the goal is vague (e.g. "travel somewhere", "buy something") ask for specifics
4. Do NOT ask for info already present in the goal
5. If the goal is clear enough, return ok=true with no questions

Return a JSON object:
- "ok": true if goal is clear (no questions needed), false if clarification needed
- "corrected_goal": the goal with spelling fixed (same if no changes needed)
- "questions": array of up to 3 missing fields, each with:
  - "key": short identifier (e.g. "destination", "duration")
  - "question": friendly question to ask the user
  - "chips": 4-6 quick-pick options relevant to context

Examples of clear goals (ok=true): "4 day trip to Goa", "buy MacBook under 1 lakh", "relocate to Bengaluru next month"
Examples of unclear goals (ok=false): "travel", "buy gadget", "plan something", "event"."""

    result = _gemini_to_json(prompt, "", max_tokens=600, response_schema=CLARIFY_SCHEMA)
    if not result or not isinstance(result, dict):
        return {"ok": True}  # fail open — never block generation
    return result


def fetch_travel_packages(p: dict[str, Any]) -> list[dict] | None:
    """
    Use Gemini + Google Search to find real current flight & hotel prices
    and return 3 combinable packages (budget / comfort / premium).
    Each package has flight, hotel, and estimated extras so the user
    sees an actual bookable combination with sources.
    """
    origin     = p.get("origin", "Delhi")
    duration   = max(1, int(p.get("duration", 3)))
    goal       = p.get("goal", "")
    dest       = _extract_destination(goal) or "Goa"
    nights     = max(1, duration - 1)  # minimum 1 night even for 1-day trips
    travellers = max(1, int(p.get("travellers", 1)))
    transport  = p.get("transport", "recommend")
    # date info already on p — used in pax/date note below

    pax_note = f"{travellers} traveller{'s' if travellers > 1 else ''}"
    departure_date = p.get("departure_date", "")
    date_flex      = p.get("date_flex", "fixed")
    date_note = ""
    if departure_date:
        date_note = f" departing {departure_date}"
        if date_flex != "fixed":
            date_note += f" (flexible by {date_flex})"
    if transport == "recommend":
        transport_note = "Compare flight vs train vs bus vs cab and pick the best value option"
    else:
        transport_note = f"Use {transport} as the mode of transport"

    prompt = (
        f"You are a travel research assistant with knowledge of Indian transport and hotels. "
        f"Give realistic current prices for a {duration}-day trip from {origin} to {dest} ({nights} nights) for {pax_note}{date_note}.\n\n"
        f"{transport_note}.\n\n"
        f"For Budget tier: use bus or sleeper train + hostel/OYO/guesthouse (minimum 3/5 guest rating). "
        f"For Comfort tier: use AC train or flight + 3-star hotel (minimum 3.5/5 rating on Booking.com/MakeMyTrip). "
        f"For Premium tier: use best flight + 4-5 star hotel (minimum 4/5 rating).\n\n"
        f"IMPORTANT: Only suggest hotels with at least a 3/5 rating. Include the hotel star rating or guest score.\n\n"
        f"For transport: name the SPECIFIC service (e.g. 'IndiGo 6E-234', 'Rajdhani Express 12951', 'KSRTC Sleeper', 'Ola Outstation'). "
        f"Name the cheapest booking site (MakeMyTrip/Ixigo/IRCTC/RedBus/GoIbibo). "
        f"Scale transport price by {travellers} traveller(s).\n\n"
        f"For hotels: the 'hotels' array in the JSON MUST contain EXACTLY 2 entries per tier (2 different real properties). "
        f"Name each property specifically (e.g. 'The Funky Monkey Hostel 4.2★', 'Lemon Tree Hotel 4/5'). "
        f"Name the site with the lowest per-night price (MakeMyTrip/Booking.com/OYO/Agoda/Goibibo). "
        f"Include the area/neighbourhood and rating for each hotel. Minimum 3/5 rating.\n\n"
        f"Also estimate typical per-day costs in {dest}: food, local transport, activities (INR integers).\n\n"
        f"CRITICAL: Each package's 'hotels' array must have exactly 2 objects. Never return just 1 hotel per tier."
    )

    raw = _gemini_to_json(prompt, "", max_tokens=2000, response_schema=PACKAGES_RESPONSE_SCHEMA)
    if not raw or not isinstance(raw.get("packages"), list):
        return None

    # Compute totals if model left them as 0
    extras = raw.get("per_day_extras") or {}
    daily_extra = (
        int(extras.get("food", 0)) +
        int(extras.get("local_transport", 0)) +
        int(extras.get("activities", 0))
    )
    nights_val = int(raw.get("nights", nights))

    packages = []
    for pkg in raw["packages"]:
        if not isinstance(pkg, dict):
            continue
        fp  = int(pkg.get("flight_price", 0))
        # Support both old single-hotel and new hotels array
        raw_hotels = pkg.get("hotels") or []
        if not raw_hotels and pkg.get("hotel_name"):
            raw_hotels = [{"hotel_name": pkg["hotel_name"], "hotel_address": pkg.get("hotel_address",""),
                           "hotel_per_night": pkg.get("hotel_per_night", 0),
                           "hotel_source": pkg.get("hotel_source",""), "hotel_rating": ""}]
        if fp <= 0 and not raw_hotels:
            continue

        dest_slug   = dest.lower().replace(" ", "-")
        origin_slug = origin.lower().replace(" ", "-")
        dest_up     = dest.replace("-", " ").title()
        origin_up   = origin.replace("-", " ").title()
        transport_mode = (pkg.get("transport_mode") or "flight").lower()
        fs = (pkg.get("flight_source") or "").lower()

        # Build transport booking URL
        if "train" in transport_mode or "irctc" in fs:
            transport_url = "https://www.irctc.co.in/nget/train-search"
        elif "bus" in transport_mode:
            transport_url = (
                f"https://www.redbus.in/bus-tickets/{origin_slug}-to-{dest_slug}" if "redbus" in fs else
                f"https://www.abhibus.com/bus_search/{origin_up}-to-{dest_up}/" if "abhibus" in fs else
                f"https://www.ixigo.com/bus/{origin_slug}-to-{dest_slug}/bus-tickets"
            )
        elif "cab" in transport_mode:
            transport_url = "https://www.olacabs.com/outstation"
        else:
            transport_url = (
                f"https://www.makemytrip.com/flights/{origin_up}-to-{dest_up}.html" if "makemytrip" in fs else
                f"https://www.cleartrip.com/flights/results?from={origin_up}&to={dest_up}&adults=1" if "cleartrip" in fs else
                f"https://www.goibibo.com/flights/search/{origin_up}-to-{dest_up}-cheap-flights/" if "goibibo" in fs else
                f"https://www.ixigo.com/flight/{origin_slug}-to-{dest_slug}/flights-from-{origin_slug}-to-{dest_slug}"
            )

        def build_hotel_url(hname: str, hsource: str) -> str:
            hs = hsource.lower()
            hq = (hname + " " + dest_up).strip().replace(" ", "+")
            if "oyo" in hs:      return f"https://www.oyorooms.com/search?location={dest_up}&q={hname.replace(' ', '+')}"
            if "makemytrip" in hs: return f"https://www.makemytrip.com/hotels/{dest_slug}-hotels.html?query={hname.replace(' ', '+')}"
            if "booking" in hs:  return f"https://www.booking.com/search.html?ss={hq}"
            if "goibibo" in hs:  return f"https://www.goibibo.com/hotels/hotels-in-{dest_slug}/?q={hname.replace(' ', '+')}"
            if "agoda" in hs:    return f"https://www.agoda.com/search?city={dest_up}&q={hname.replace(' ', '+')}"
            return f"https://www.booking.com/search.html?ss={hq}"

        hotels_out = []
        for h in raw_hotels[:3]:  # max 3 options
            hpp = int(h.get("hotel_per_night", 0))
            hotels_out.append({
                "hotel_name":      h.get("hotel_name", ""),
                "hotel_address":   h.get("hotel_address", ""),
                "hotel_per_night": hpp,
                "hotel_source":    h.get("hotel_source", ""),
                "hotel_rating":    h.get("hotel_rating", ""),
                "hotel_url":       build_hotel_url(h.get("hotel_name",""), h.get("hotel_source","")),
            })

        # Total uses cheapest hotel option for estimate
        hpp0 = hotels_out[0]["hotel_per_night"] if hotels_out else 0
        total = pkg.get("total") or (fp + hpp0 * nights_val + daily_extra * nights_val)

        packages.append({
            "tier":             pkg.get("tier", ""),
            "transport_mode":   transport_mode,
            "transport_name":   pkg.get("transport_name", pkg.get("flight_operator", "")),
            "transport_detail": pkg.get("transport_detail", ""),
            "flight_price":     fp,
            "flight_operator":  pkg.get("flight_operator", ""),
            "flight_source":    pkg.get("flight_source", ""),
            "flight_url":       transport_url,
            "hotels":           hotels_out,
            # Keep legacy single fields for backwards compat
            "hotel_per_night":  hpp0,
            "hotel_name":       hotels_out[0]["hotel_name"] if hotels_out else "",
            "hotel_address":    hotels_out[0]["hotel_address"] if hotels_out else "",
            "hotel_source":     hotels_out[0]["hotel_source"] if hotels_out else "",
            "hotel_url":        hotels_out[0]["hotel_url"] if hotels_out else "",
            "nights":           nights_val,
            "daily_extras":     daily_extra,
            "total":            int(total),
        })

    return packages if packages else None


def _mock_gadget_prices(goal: str, budget: int) -> dict:
    """Return realistic mock gadget models for testing when Gemini quota is exhausted."""
    g = goal.lower()
    is_phone    = any(w in g for w in ["phone","mobile","iphone","samsung","oneplus"])
    is_tablet   = any(w in g for w in ["tablet","ipad"])
    is_headphone= any(w in g for w in ["headphone","earphone","airpod","earbuds"])
    is_gaming   = any(w in g for w in ["gaming","game","rtx","gtx","nvidia","amd rx","rgb"])
    b = budget

    if is_phone:
        models = [
            {"name":"Samsung Galaxy A55","variant":"8GB RAM, 128GB, 5G","tag":"Best value",
             "image_url":"","lowest_site":"Flipkart","lowest_url":"https://www.flipkart.com/mobiles",
             "prices":{"Flipkart":34999,"Amazon":35490,"Croma":36990,"Reliance Digital":36500,"TataCliq":35200},
             "key_specs":["Exynos 1480","8GB RAM","128GB UFS","6.6\" Super AMOLED","5000mAh","50MP camera"],
             "pros":["Excellent display","5G ready","4 years OS updates"],"cons":["No charger in box","Plastic back"],
             "card_offers":[{"bank":"HDFC","card":"Credit Card","offer":"10% off","max_discount":2000,"site":"Flipkart"}]},
            {"name":"OnePlus Nord CE4","variant":"8GB RAM, 256GB, 5G","tag":"Performance pick",
             "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=oneplus",
             "prices":{"Flipkart":24999,"Amazon":24499,"Croma":25990,"Reliance Digital":25500,"TataCliq":24800},
             "key_specs":["Snapdragon 7s Gen 3","8GB RAM","256GB UFS","6.7\" AMOLED","5500mAh","100W charging"],
             "pros":["100W fast charging","Clean OxygenOS","Great battery life"],"cons":["Average camera","No wireless charging"],
             "card_offers":[]},
        ]
    elif is_headphone:
        models = [
            {"name":"Sony WH-1000XM5","variant":"Over-ear ANC Wireless","tag":"Premium pick",
             "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=sony+wh1000xm5",
             "prices":{"Flipkart":26990,"Amazon":25990,"Croma":27990,"Reliance Digital":27500,"TataCliq":26500},
             "key_specs":["Industry-leading ANC","30hr battery","LDAC","Multipoint","Foldable","USB-C"],
             "pros":["Best ANC in class","Excellent call quality","Lightweight"],"cons":["Expensive","No IP rating"],
             "card_offers":[{"bank":"ICICI","card":"Credit Card","offer":"₹2000 instant discount","max_discount":2000,"site":"Croma"}]},
        ]
    elif is_gaming:
        # Gaming laptops — pick based on budget
        if b >= 120000:
            models = [
                {"name":"ASUS ROG Strix G16","variant":"Intel i7-13650HX, 16GB DDR5, RTX 4060, 512GB SSD","tag":"Best value gaming",
                 "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=asus+rog+strix+g16+rtx+4060",
                 "prices":{"Amazon":124990,"Flipkart":126990,"Croma":129990,"Reliance Digital":127000,"TataCliq":125500},
                 "key_specs":["i7-13650HX","16GB DDR5","RTX 4060 8GB","16\" FHD 165Hz","512GB NVMe","Win11"],
                 "pros":["Excellent 1080p gaming performance","MUX switch","Good cooling"],
                 "cons":["Runs warm under sustained load","Heavy at 2.3kg"],
                 "card_offers":[{"bank":"HDFC","card":"Credit Card","offer":"5% off","max_discount":3000,"site":"Amazon"}]},
                {"name":"Lenovo LOQ 15IRX9","variant":"Intel i5-13450HX, 16GB, RTX 4060, 512GB SSD","tag":"Budget gaming pick",
                 "image_url":"","lowest_site":"Flipkart","lowest_url":"https://www.flipkart.com/search?q=lenovo+loq+rtx+4060",
                 "prices":{"Flipkart":109990,"Amazon":111990,"Croma":114990,"Reliance Digital":113000,"TataCliq":110500},
                 "key_specs":["i5-13450HX","16GB DDR5","RTX 4060 8GB","15.6\" FHD 144Hz","512GB NVMe","Win11"],
                 "pros":["RTX 4060 at competitive price","144Hz display","Decent battery"],
                 "cons":["Throttles under extreme load","Plastic chassis"],
                 "card_offers":[]},
                {"name":"MSI Cyborg 15","variant":"Intel i7-12650H, 16GB, RTX 4060, 512GB SSD","tag":"Stylish gaming",
                 "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=msi+cyborg+15+rtx+4060",
                 "prices":{"Amazon":116990,"Flipkart":118990,"Croma":120990,"Reliance Digital":119000,"TataCliq":117500},
                 "key_specs":["i7-12650H","16GB DDR5","RTX 4060 8GB","15.6\" FHD 144Hz","512GB NVMe","Win11"],
                 "pros":["Unique transparent design","Good port selection","Solid gaming performance"],
                 "cons":["Shorter battery life","Screen could be brighter"],
                 "card_offers":[{"bank":"SBI","card":"Credit Card","offer":"₹2000 instant off","max_discount":2000,"site":"Croma"}]},
            ]
        elif b >= 80000:
            models = [
                {"name":"ASUS TUF Gaming F15","variant":"Intel i5-13500H, 16GB, RTX 4060, 512GB SSD","tag":"Best value gaming",
                 "image_url":"","lowest_site":"Flipkart","lowest_url":"https://www.flipkart.com/search?q=asus+tuf+f15+rtx+4060",
                 "prices":{"Flipkart":82990,"Amazon":84990,"Croma":86990,"Reliance Digital":85500,"TataCliq":83500},
                 "key_specs":["i5-13500H","16GB DDR4","RTX 4060 8GB","15.6\" FHD 144Hz","512GB NVMe","Win11"],
                 "pros":["Excellent price-to-performance","MIL-STD durability","Good cooling"],
                 "cons":["Display colour accuracy average","Heavy charger"],
                 "card_offers":[{"bank":"HDFC","card":"Credit Card","offer":"10% off up to ₹3000","max_discount":3000,"site":"Flipkart"}]},
                {"name":"Lenovo IdeaPad Gaming 3","variant":"Ryzen 5 7535HS, 16GB, RTX 4050, 512GB SSD","tag":"Budget gaming pick",
                 "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=lenovo+ideapad+gaming+3+rtx+4050",
                 "prices":{"Amazon":72990,"Flipkart":73990,"Croma":75990,"Reliance Digital":74500,"TataCliq":73500},
                 "key_specs":["Ryzen 5 7535HS","16GB DDR5","RTX 4050 6GB","15.6\" FHD 144Hz","512GB NVMe","Win11"],
                 "pros":["Great at 1080p medium-high settings","Affordable","16GB RAM standard"],
                 "cons":["RTX 4050 limited at ultra settings","Dim display"],
                 "card_offers":[]},
                {"name":"HP Victus 16","variant":"Intel i5-13420H, 16GB, RTX 4060, 512GB SSD","tag":"Reliable gaming",
                 "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=hp+victus+16+rtx+4060",
                 "prices":{"Amazon":84990,"Flipkart":85990,"Croma":87990,"Reliance Digital":86500,"TataCliq":85500},
                 "key_specs":["i5-13420H","16GB DDR4","RTX 4060 8GB","16.1\" FHD 144Hz","512GB NVMe","Win11"],
                 "pros":["Good display size","HP build quality","RTX 4060 at this price"],
                 "cons":["Fan noise at load","Plastic body"],
                 "card_offers":[{"bank":"ICICI","card":"Credit Card","offer":"5% cashback","max_discount":2500,"site":"Amazon"}]},
            ]
        else:  # under 80k gaming
            models = [
                {"name":"ASUS TUF Gaming A15","variant":"Ryzen 5 7535HS, 16GB, RTX 4050, 512GB SSD","tag":"Best value gaming",
                 "image_url":"","lowest_site":"Flipkart","lowest_url":"https://www.flipkart.com/search?q=asus+tuf+a15+rtx+4050",
                 "prices":{"Flipkart":69990,"Amazon":71990,"Croma":73990,"Reliance Digital":72500,"TataCliq":70500},
                 "key_specs":["Ryzen 5 7535HS","16GB DDR5","RTX 4050 6GB","15.6\" FHD 144Hz","512GB NVMe","Win11"],
                 "pros":["Top gaming perf under ₹70k","Great battery for gaming laptop","MIL-STD build"],
                 "cons":["Display not the brightest","No Thunderbolt"],
                 "card_offers":[{"bank":"HDFC","card":"Credit Card","offer":"10% off","max_discount":2000,"site":"Flipkart"}]},
                {"name":"Lenovo IdeaPad Gaming 3","variant":"Ryzen 5 6600H, 16GB, RTX 3050, 512GB SSD","tag":"Entry gaming pick",
                 "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=lenovo+ideapad+gaming+3+rtx+3050",
                 "prices":{"Amazon":59990,"Flipkart":60990,"Croma":62990,"Reliance Digital":61500,"TataCliq":60500},
                 "key_specs":["Ryzen 5 6600H","16GB DDR5","RTX 3050 4GB","15.6\" FHD 120Hz","512GB NVMe","Win11"],
                 "pros":["Cheapest dedicated GPU laptop","Good build","Upgradeable RAM/SSD"],
                 "cons":["RTX 3050 limited in AAA games","Dim 250nits display"],
                 "card_offers":[]},
                {"name":"HP Victus 15","variant":"Ryzen 5 5600H, 8GB, GTX 1650, 512GB SSD","tag":"Starter gaming",
                 "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=hp+victus+15+gtx+1650",
                 "prices":{"Amazon":54990,"Flipkart":55990,"Croma":57990,"Reliance Digital":56500,"TataCliq":55500},
                 "key_specs":["Ryzen 5 5600H","8GB DDR4","GTX 1650 4GB","15.6\" FHD 144Hz","512GB SSD","Win11"],
                 "pros":["144Hz display","HP brand reliability","Decent 1080p gaming at medium"],
                 "cons":["Only 8GB RAM","GTX 1650 aging quickly","No ray tracing"],
                 "card_offers":[{"bank":"SBI","card":"Debit Card","offer":"5% cashback","max_discount":1500,"site":"Amazon"}]},
            ]
    else:  # generic laptop default
        models = [
            {"name":"Lenovo IdeaPad Slim 5","variant":"Intel i5-12th Gen, 16GB RAM, 512GB SSD","tag":"Best value",
             "image_url":"","lowest_site":"Flipkart","lowest_url":"https://www.flipkart.com/laptops",
             "prices":{"Flipkart":52990,"Amazon":53490,"Croma":54990,"Reliance Digital":55000,"TataCliq":53000},
             "key_specs":["Intel i5-1235U","16GB DDR4","512GB NVMe","15.6\" FHD IPS","Backlit KB","Win11"],
             "pros":["Great specs-to-price ratio","Good battery (~8hr)","Reliable after-sales"],
             "cons":["Average build (plastic)","No dedicated GPU"],
             "card_offers":[{"bank":"HDFC","card":"Credit Card","offer":"10% instant discount","max_discount":1500,"site":"Flipkart"}]},
            {"name":"ASUS VivoBook 15","variant":"AMD Ryzen 5 5500U, 8GB RAM, 512GB SSD","tag":"Budget pick",
             "image_url":"","lowest_site":"Flipkart","lowest_url":"https://www.flipkart.com/laptops",
             "prices":{"Flipkart":44990,"Amazon":45490,"Croma":46990,"Reliance Digital":47000,"TataCliq":45000},
             "key_specs":["Ryzen 5 5500U","8GB DDR4","512GB SSD","15.6\" FHD","Thin 1.7kg","Win11"],
             "pros":["Very affordable","Light and portable","Good display brightness"],
             "cons":["Only 8GB RAM","Plastic build","Smaller battery"],
             "card_offers":[]},
            {"name":"HP Pavilion 15","variant":"Intel i5-12th Gen, 8GB RAM, 512GB SSD","tag":"Reliable choice",
             "image_url":"","lowest_site":"Amazon","lowest_url":"https://www.amazon.in/s?k=hp+pavilion+15",
             "prices":{"Flipkart":57990,"Amazon":56490,"Croma":58990,"Reliance Digital":59000,"TataCliq":57000},
             "key_specs":["Intel i5-1235U","8GB DDR4","512GB SSD","15.6\" FHD","HP Fast Charge","Win11"],
             "pros":["Solid HP build quality","Good keyboard","Fast charging"],
             "cons":["8GB RAM only","Runs warm under load"],
             "card_offers":[{"bank":"SBI","card":"Debit Card","offer":"5% cashback","max_discount":1000,"site":"Amazon"}]},
        ]
    low = min(min(m["prices"].values()) for m in models)
    high = max(max(m["prices"].values()) for m in models)
    return {
        "models": models,
        "Warranty": {"low": 2000, "high": 5000, "typical": 3500, "source": "Mock"},
        "Accessories": {"low": 1000, "high": 3000, "typical": 2000, "source": "Mock"},
        "Discounts": {"low": 500, "high": 3000, "typical": 1500, "source": "Mock"},
        "Resale buffer": {"low": 1000, "high": 4000, "typical": 2000, "source": "Mock"},
        "low": low, "high": high, "typical": (low + high) // 2, "source": "Sample data (Gemini quota exceeded)",
    }


def fetch_real_prices(p: dict[str, Any]) -> dict[str, Any] | None:
    """
    For non-travel types: fetch bucket-level price ranges via Gemini Search.
    For travel: use fetch_travel_packages instead (returns packages, not this dict).
    """
    if p.get("type") == "travel":
        return None  # handled separately by fetch_travel_packages

    goal_type = p["type"]
    origin    = p.get("origin", "Delhi")
    goal_text = p.get("goal", "")

    if goal_type == "gadget":
        research_prompt = (
            f"Search Google for the BEST options in India for: {goal_text}\n\n"
            f"Find 3 to 5 SPECIFIC recommended models (actual product names with variant/specs) "
            f"across different price ranges and use cases. For each model find:\n"
            f"1. EXACT current price on Flipkart, Amazon India, Croma, Reliance Digital, TataCliq\n"
            f"2. Which site has the LOWEST price right now and the direct product URL on that site\n"
            f"3. A product image CDN URL (from Amazon m.media-amazon.com/images/ or Flipkart rukminim2.flixcdn.com/image/)\n"
            f"4. Key specs (processor, RAM, storage, display, battery etc)\n"
            f"5. 2-4 pros and 1-3 cons for each model\n"
            f"6. Active bank/card discount offers (e.g. HDFC 10% up to ₹1500 on Flipkart)\n"
            f"7. Tag each model: 'Best value', 'Budget pick', 'Premium pick', 'Performance beast', etc.\n\n"
            f"Also find: extended warranty cost (1-2 yr), essential accessories bundle price.\n"
            f"Give REAL model names like 'Lenovo IdeaPad Slim 5 Gen 8 (Intel i5-1235U, 16GB, 512GB SSD)' "
            f"not generic names. Include exact rupee prices from live listings."
        )
        research = _gemini_raw_text(research_prompt, max_tokens=2000)
        if not research:
            return None
        result = _gemini_to_json(research, "", max_tokens=1500, response_schema=GADGET_RESPONSE_SCHEMA)
        return result
    elif goal_type == "relocation":
        dest = _extract_destination(goal_text) or "Bangalore"
        research_prompt = (
            f"Search Google for CURRENT (2024-2025) relocation costs in India from {origin} to {dest}. "
            f"Find realistic ranges for: security deposit for 1BHK/2BHK, packers & movers cost, "
            f"basic furniture set, monthly commute cost, setup/utility deposits. "
            f"Cite actual sites or listings where possible."
        )
        research = _gemini_raw_text(research_prompt, max_tokens=900)
        if not research:
            return None
        result = _gemini_to_json(research, "", max_tokens=600, response_schema=RELOCATION_RESPONSE_SCHEMA)
    else:  # event
        research_prompt = (
            f"Search Google for CURRENT (2024-2025) event costs in India for: {goal_text}. "
            f"Find realistic ranges for: venue rental, catering per plate, decoration, photography, logistics. "
            f"Cite actual vendors or platforms where possible."
        )
        research = _gemini_raw_text(research_prompt, max_tokens=900)
        if not research:
            return None
        result = _gemini_to_json(research, "", max_tokens=600, response_schema=EVENT_RESPONSE_SCHEMA)

    return result

def call_gemini(p: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    url  = GEMINI_API_URL.format(model=GEMINI_MODEL, key=api_key)
    body = json.dumps({
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": _user_msg(p)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 4096,
            "temperature": 0.4,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = _parse_llm_text(text)
        parsed["mode"]  = "gemini"
        parsed["model"] = GEMINI_MODEL
        return parsed
    except json.JSONDecodeError as e:
        print(f"[gemini] JSON parse error: {e}", flush=True)
        return None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        print(f"[gemini] HTTP {e.code}: {body_text[:200]}", flush=True)
        return None
    except Exception as e:
        print(f"[gemini] error: {e}", flush=True)
        return None

# ── CLAUDE AI CALL ───────────────────────────────────────────────────────────

def call_claude(p: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        return {"mode": "error", "reason": "anthropic package not installed. Run: pip install anthropic"}

    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _user_msg(p)}],
        )
        text = msg.content[0].text if msg.content else ""
        parsed = _parse_llm_text(text)
        parsed["mode"]  = "claude"
        parsed["model"] = MODEL
        return parsed
    except json.JSONDecodeError as e:
        return {"mode": "claude_parse_error", "reason": str(e), "summary": {"headline": "Claude responded but JSON parse failed; local optimizer used."}}
    except Exception as e:
        return {"mode": "claude_error", "reason": str(e), "summary": {"headline": "Claude call failed; local optimizer used."}}

# ── HTTP SERVER ───────────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "application/javascript", ".css": "text/css"}
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: N802
        print(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else ''}")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if self.path == "/api/health":
            has_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
            has_gemini = bool(os.getenv("GEMINI_API_KEY"))
            self.send_json({
                "ok": True,
                "llm_configured": has_claude or has_gemini,
                "provider": "claude" if has_claude else ("gemini" if has_gemini else "none"),
                "model": MODEL if has_claude else (GEMINI_MODEL if has_gemini else "local"),
                "routes": ["/api/health", "/api/plan", "/api/history"],
            })
            return
        if self.path == "/api/history":
            self.send_json({"history": db_load_history(12)})
            return
        if self.path.startswith("/api/imgproxy?url="):
            raw_url = self.path[len("/api/imgproxy?url="):]
            import urllib.parse as _up
            img_url = _up.unquote(raw_url)
            allowed = ("m.media-amazon.com", "rukminim2.flixcdn.com", "rukminim1.flixcdn.com",
                       "images-na.ssl-images-amazon.com", "croma.com", "tatacliq.com",
                       "images.unsplash.com", "i.imgur.com",
                       "duckduckgo.com", "external-content.duckduckgo.com",
                       "upload.wikimedia.org", "wikipedia.org",
                       "cdn.mos.cms.futurecdn.net", "static.digit.in",
                       "images.gsmarena.com", "i.rtings.com")
            from urllib.parse import urlparse as _uparse
            host = _uparse(img_url).hostname or ""
            if not any(host.endswith(a) for a in allowed):
                self.send_json({"error": "disallowed"}, HTTPStatus.FORBIDDEN)
                return
            try:
                req = urllib.request.Request(img_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; CostPilot/1.0)",
                    "Referer": img_url,
                })
                with urllib.request.urlopen(req, timeout=8) as r:
                    ctype = r.headers.get("Content-Type", "image/jpeg")
                    data = r.read(2 * 1024 * 1024)  # max 2MB
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_json({"error": str(e)}, HTTPStatus.BAD_GATEWAY)
            return
        if self.path in {"/", "/index.html"}:
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path == "/api/clarify":
            try:
                body = read_json(self)
                goal = (body.get("goal") or "").strip()
                type_ = (body.get("type") or "travel").strip()
                budget = body.get("budget", "")
                result = _clarify_goal(goal, type_, budget)
                self.send_json(result)
            except Exception as exc:
                self.send_json({"ok": True})  # fail open — don't block generation
            return
        if self.path != "/api/plan":
            self.send_json({"error": "Unknown route"}, HTTPStatus.NOT_FOUND)
            return
        try:
            import concurrent.futures
            p = normalize(read_json(self))
            llm = None
            live_prices     = None
            travel_packages = None
            # Run AI plan + price fetch in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                ai_future  = ex.submit(lambda: call_claude(p) or call_gemini(p))
                pkg_future = ex.submit(fetch_travel_packages, p) if p["type"] == "travel" else None
                prc_future = ex.submit(fetch_real_prices, p)    if p["type"] != "travel" else None
                try:
                    llm = ai_future.result(timeout=30)
                except Exception as exc:
                    llm = {"mode": "error", "reason": str(exc), "summary": {"headline": "AI call failed; local optimizer used."}}
                if pkg_future:
                    try:
                        travel_packages = pkg_future.result(timeout=22)
                    except Exception:
                        travel_packages = None
                if prc_future:
                    try:
                        live_prices = prc_future.result(timeout=22)
                    except Exception:
                        live_prices = None
                # DEV FALLBACK: inject mock gadget models when Gemini is rate-limited
                if p.get("type") == "gadget" and not live_prices:
                    live_prices = _mock_gadget_prices(p.get("goal", ""), p.get("budget", 60000))
            self.send_json(full_result(p, llm, live_prices, travel_packages))
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

# ── ENTRY POINT ──────────────────────────────────────────────────────────────

def main():
    port = int(os.getenv("PORT", "4173"))
    os.chdir(ROOT)
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    has_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    db_size    = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    if has_claude:   ai_label = f"Claude {MODEL}"
    elif has_gemini: ai_label = f"Gemini {GEMINI_MODEL}"
    else:            ai_label = "Local optimizer  (add ANTHROPIC_API_KEY or GEMINI_API_KEY to .env)"
    print(f"\n  CostPilot AI  →  http://localhost:{port}")
    print(f"  AI backend    →  {ai_label}")
    print(f"  Database      →  {DB_PATH.name} ({db_size:,} bytes)")
    print(f"  History       →  {len(db_load_history(999))} saved plans\n")
    server.serve_forever()

if __name__ == "__main__":
    main()
