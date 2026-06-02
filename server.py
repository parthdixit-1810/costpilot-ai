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

def db_load_history(limit: int = 12) -> list[dict[str, Any]]:
    with get_db() as cx:
        rows = cx.execute(
            "SELECT title, budget, engine, type, goal, created_at FROM plans ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

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
    return {
        "goal":     str(raw.get("goal") or "").strip()[:1200],
        "type":     t,
        "budget":   max(1, int(raw.get("budget") or 25000)),
        "duration": max(1, int(raw.get("duration") or 1)),
        "origin":   str(raw.get("origin") or "Delhi")[:80],
        "priority": str(raw.get("priority") or "balanced"),
        "options":  raw.get("options") if isinstance(raw.get("options"), dict) else {},
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
            "Claude AI + optimizer" if llm and llm.get("mode") == "claude"
            else "Gemini AI + optimizer" if llm and llm.get("mode") == "gemini"
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
    }

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
    '  "plans": {\n'
    '    "cheapest": {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]},\n'
    '    "fastest":  {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]},\n'
    '    "value":    {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]},\n'
    '    "premium":  {"explanation": string, "tradeoffs": [string,string,string], "savings": [string,string,string]}\n'
    "  }\n"
    "}\n"
    "Be specific to the Indian market, destination, and budget. "
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

def _gemini_search(prompt: str, max_tokens: int = 700) -> dict | None:
    """Call Gemini with Google Search grounding; return parsed JSON or None."""
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
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        for fence in ("```json", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
        return json.loads(text.rstrip("`").strip())
    except Exception as e:
        print(f"[gemini_search] error: {e}", flush=True)
        return None


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
    nights     = max(1, duration - 1)
    travellers = max(1, int(p.get("travellers", 1)))
    transport  = p.get("transport", "recommend")

    pax_note = f"{travellers} traveller{'s' if travellers > 1 else ''}"
    if transport == "recommend":
        transport_note = "Compare flight vs train vs bus vs cab and pick the best value option"
    else:
        transport_note = f"Use {transport} as the mode of transport"

    prompt = (
        f"Search Google right now for the LOWEST current prices (INR) for a {duration}-day trip "
        f"from {origin} to {dest} ({nights} nights) for {pax_note}.\n\n"
        f"{transport_note}.\n\n"
        f"Find:\n"
        f"A) Budget option: cheapest transport {origin}→{dest} (consider all modes: flight/train/bus/cab), "
        f"cheapest decent hotel/hostel/OYO in {dest} per night\n"
        f"B) Comfort option: mid-range transport option, 3-star hotel per night\n"
        f"C) Premium option: premium transport or upgrade, 4-5 star hotel per night\n\n"
        f"Scale all prices by {travellers} traveller(s) where applicable (transport, food).\n"
        f"Also estimate per day: food (INR), local transport (INR), activities (INR) for {dest}.\n\n"
        f"Return ONLY this exact JSON (integers only, no ranges, use real searched values):\n"
        f'{{\n'
        f'  "destination": "{dest}",\n'
        f'  "origin": "{origin}",\n'
        f'  "nights": {nights},\n'
        f'  "per_day_extras": {{"food": 0, "local_transport": 0, "activities": 0}},\n'
        f'  "packages": [\n'
        f'    {{"tier":"Budget","flight_price":0,"flight_source":"","flight_operator":"",'
        f'"hotel_per_night":0,"hotel_source":"","hotel_name":"","total":0}},\n'
        f'    {{"tier":"Comfort","flight_price":0,"flight_source":"","flight_operator":"",'
        f'"hotel_per_night":0,"hotel_source":"","hotel_name":"","total":0}},\n'
        f'    {{"tier":"Premium","flight_price":0,"flight_source":"","flight_operator":"",'
        f'"hotel_per_night":0,"hotel_source":"","hotel_name":"","total":0}}\n'
        f'  ]\n'
        f'}}'
    )

    raw = _gemini_search(prompt, max_tokens=800)
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
        hpp = int(pkg.get("hotel_per_night", 0))
        if fp <= 0 and hpp <= 0:
            continue
        total = pkg.get("total") or (fp + hpp * nights_val + daily_extra * nights_val)
        # Build deep booking links
        dest_slug   = dest.lower().replace(" ", "-")
        origin_slug = origin.lower().replace(" ", "-")
        dest_up     = dest.replace("-", " ").title()
        origin_up   = origin.replace("-", " ").title()
        fs = (pkg.get("flight_source") or "").lower()
        hs = (pkg.get("hotel_source") or "").lower()
        flight_url = (
            f"https://www.makemytrip.com/flights/{origin_up}-to-{dest_up}.html" if "makemytrip" in fs else
            f"https://www.cleartrip.com/flights/results?from={origin_up}&to={dest_up}&adults=1" if "cleartrip" in fs else
            f"https://www.goibibo.com/flights/search/{origin_up}-to-{dest_up}-cheap-flights/" if "goibibo" in fs else
            f"https://www.ixigo.com/flight/{origin_slug}-to-{dest_slug}/flights-from-{origin_slug}-to-{dest_slug}"
        )
        hotel_url = (
            f"https://www.oyorooms.com/search?location={dest_up}" if "oyo" in hs else
            f"https://www.makemytrip.com/hotels/{dest_slug}-hotels.html" if "makemytrip" in hs else
            f"https://www.booking.com/search.html?ss={dest_up}" if "booking" in hs else
            f"https://www.agoda.com/search?city={dest_up}" if "agoda" in hs else
            f"https://www.makemytrip.com/hotels/{dest_slug}-hotels.html"
        )
        packages.append({
            "tier":             pkg.get("tier", ""),
            "flight_price":     fp,
            "flight_operator":  pkg.get("flight_operator", ""),
            "flight_source":    pkg.get("flight_source", ""),
            "flight_url":       flight_url,
            "hotel_per_night":  hpp,
            "hotel_name":       pkg.get("hotel_name", ""),
            "hotel_source":     pkg.get("hotel_source", ""),
            "hotel_url":        hotel_url,
            "nights":           nights_val,
            "daily_extras":     daily_extra,
            "total":            int(total),
        })

    print(f"[packages] fetched {len(packages)} travel packages for {origin}→{dest}", flush=True)
    return packages if packages else None


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
        prompt = (
            f"Search Google for CURRENT (2024-2025) price in India for: {goal_text}. "
            f"Find prices on Flipkart, Amazon India, Croma, Reliance Digital. "
            f"Return ONLY this JSON, no markdown:\n"
            f'{{"Device":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Warranty":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Accessories":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Discounts":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Resale buffer":{{"low":0,"high":0,"typical":0,"source":""}}}}'
        )
    elif goal_type == "relocation":
        dest = _extract_destination(goal_text) or "Bangalore"
        prompt = (
            f"Search Google for CURRENT (2024-2025) relocation costs in India from {origin} to {dest}. "
            f"Find: security deposit for 1BHK/2BHK, packers & movers cost, "
            f"basic furniture set, monthly commute cost, setup/utility deposits. "
            f"Return ONLY this JSON, no markdown:\n"
            f'{{"Deposit":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Moving":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Furniture":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Commute":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Setup":{{"low":0,"high":0,"typical":0,"source":""}}}}'
        )
    else:  # event
        prompt = (
            f"Search Google for CURRENT (2024-2025) event costs in India for: {goal_text}. "
            f"Find: venue rental, catering per plate, decoration, photography, logistics. "
            f"Return ONLY this JSON, no markdown:\n"
            f'{{"Venue":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Catering":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Decor":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Photo":{{"low":0,"high":0,"typical":0,"source":""}},'
            f'"Logistics":{{"low":0,"high":0,"typical":0,"source":""}}}}'
        )

    result = _gemini_search(prompt)
    if result:
        print(f"[prices] fetched live prices for {goal_type}", flush=True)
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
            "maxOutputTokens": 1024,
            "temperature": 0.4,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
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
        if self.path in {"/", "/index.html"}:
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):  # noqa: N802
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
                    llm = ai_future.result(timeout=35)
                except Exception as exc:
                    llm = {"mode": "error", "reason": str(exc), "summary": {"headline": "AI call failed; local optimizer used."}}
                if pkg_future:
                    try:
                        travel_packages = pkg_future.result(timeout=25)
                    except Exception:
                        travel_packages = None
                if prc_future:
                    try:
                        live_prices = prc_future.result(timeout=25)
                    except Exception:
                        live_prices = None
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
