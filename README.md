# CostPilot AI

CostPilot AI is a dynamic full-stack prototype for goal-based cost optimization. The frontend talks to a local Python backend, the backend exposes planning routes, and the LLM bridge uses the OpenAI Responses API when `OPENAI_API_KEY` is configured.

## Run

```bash
python3 server.py
```

Open:

```text
http://localhost:4173
```

Optional live LLM mode:

```bash
OPENAI_API_KEY=sk-... python3 server.py
```

Optional model override:

```bash
OPENAI_MODEL=gpt-5.4-mini python3 server.py
```

If no API key is set, the app still runs with a deterministic optimizer so the product flow remains usable.

## Routes

- `GET /` - dynamic web app
- `GET /api/health` - backend and LLM configuration status
- `GET /api/history` - recent local planning runs
- `POST /api/plan` - generate optimized route plans from a goal payload

## Files

- `server.py` - HTTP server, API routes, optimizer, OpenAI Responses API bridge
- `index.html` - app shell and dashboard layout
- `styles.css` - responsive product UI
- `app.js` - frontend state, API calls, plan rendering, graph and history views
- `assets/costpilot-hero.png` - generated hero visual copied into the project
