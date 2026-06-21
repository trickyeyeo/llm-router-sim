# LLM Router Demo WebApp

Complete interactive web application demonstrating prefix-aware routing for multi-turn agentic workloads.

## Quick Start

### Prerequisites
- Docker & Docker Compose installed

### Run the Demo

```bash
# From the project root
docker-compose -f webapp/docker-compose.yml up --build
```

Then open your browser:
- **Frontend:** http://localhost:5173 (dev) or http://localhost (production)
- **Backend API:** http://localhost:8001
- **Health check:** http://localhost:8001/health

### What You'll See

1. **Parameter Controls** (left sidebar)
   - Adjust concurrent conversations (1-250)
   - Adjust turns per conversation (1-10)
   - GPU0 HBM pre-fill slider to test multi-GPU scenarios
   - Click "Run Simulation" to start

2. **Real-time Progress**
   - Progress bar showing % complete
   - Simulation time counter
   - Request count (completed/generated)

3. **GPU Utilization Cards** (live updates)
   - Side-by-side comparison: Stateless vs Stateful routing
   - HBM utilization % with color coding
   - Cache hit rate %
   - Active metrics update every heartbeat

4. **Key Metrics** (after simulation completes)
   - **Cache hit rate** — ~81% with stateful routing vs 0% stateless
   - **Block efficiency** — 30% fewer cached blocks needed (same traffic)
   - **Capacity gain** — 30% higher multitenancy on identical hardware
   - **TTFT improvement** — 22% latency reduction (decode-dominated TTFT)

5. **Comparison Charts** (overlay visualization)
   - TTFT per turn (stateless red vs stateful green)
   - HBM utilization over time
   - Cache hit rate progression
   - Throughput comparison

6. **Expert Breakdown** (accordion, auto-open)
   - Per-turn detailed metrics table
   - Routing strategy breakdown (% cache hit, affinity degraded, load balanced)
   - Per-GPU utilization metrics
   - Key findings summary

7. **PDF Export**
   - "Download Results as PDF" button appears after simulation
   - Includes all parameters, metrics, charts, and detailed findings

---

## Architecture

### Backend (FastAPI)
- Runs simulations in real-time
- Streams events via Server-Sent Events (SSE)
- Executes both stateless and stateful routing simultaneously
- Endpoint: `GET /simulate?num_sessions=5&turns_per_session=5`

### Frontend (React + TypeScript)
- Real-time visualization of simulation progress
- Smooth animations for GPU metrics and charts
- Overlay comparison charts via Recharts
- PDF export with html2canvas + jsPDF

### Data Flow
```
User (browser)
    ↓
React Frontend (displays UI, sends params)
    ↓ (GET /simulate?num_sessions=5&turns_per_session=5)
FastAPI Backend (runs simulations, emits SSE events)
    ↓ (SSE: heartbeat events with GPU state)
React Frontend (updates state, animates charts)
```

---

## Key Narrative

**The Demo Shows:**

1. **Multi-turn conversations** are common in agentic systems
2. **Stateless routing** re-computes identical system prompts and conversation history on every turn (wasteful)
3. **Prefix-aware routing** (LoadAwareRouter) caches this context and reuses it, while load-aware scoring prevents thundering herds
4. **Actual results from v1.0:**
   - 81% cache hit rate (57 out of 70 requests matched cached prefix)
   - 30% block reduction (127 cached blocks vs 183 for stateless)
   - 22% TTFT improvement (396ms → 305ms, but decode-time limited)
   - Same throughput, better efficiency = higher multitenancy capacity

---

## Development

### Hot Reload
Frontend supports hot reload during development:
```bash
cd webapp/frontend
npm install
npm run dev
```

Backend hot reload requires restart:
```bash
# In another terminal
docker-compose -f webapp/docker-compose.yml up --build
```

### Modify Parameters
Edit `webapp/frontend/src/components/ParameterPanel.tsx`:
- Change slider ranges
- Adjust default values
- Add new parameters

### Modify Simulation
Edit `webapp/main.py`:
- Change simulation time (currently 35 seconds)
- Adjust workload defaults
- Add new simulation types

---

## Troubleshooting

### Frontend won't connect to backend
- Ensure backend is running: `docker logs webapp-backend-1`
- Check CORS settings in `main.py`
- Verify API URL in frontend env

### Charts not showing
- Check browser console for errors
- Verify metrics data structure in SSE events
- Ensure Recharts is properly installed

### PDF export fails
- Ensure html2canvas and jsPDF are installed
- Check browser console for canvas rendering errors
- Try smaller viewport if running on low-memory system

### Simulation runs but shows no data
- Check that backend is emitting SSE events
- Verify EventSource connection in browser console
- Ensure both simulations completed (check console logs)

---

## Files

- `webapp/main.py` — FastAPI backend
- `webapp/frontend/` — React application
- `webapp/docker-compose.yml` — Orchestration
- `webapp/Dockerfile.backend` — Backend container
- `webapp/frontend/Dockerfile` — Frontend container
- `webapp/IMPLEMENTATION_GUIDE.md` — Technical details

---

## Next Steps

1. **Deploy to cloud** — Use Docker Compose on AWS/GCP/Azure
2. **Add more workloads** — RAG, few-shot, streaming, etc.
3. **Implement live controls** — Pause/resume, speed controls
4. **Add telemetry** — Track how many times demo is run
5. **Customize branding** — Add logos, change colors

---

## Performance

- Backend: Processes 10,000+ simulated requests per second
- Frontend: 60 FPS animations on modern browsers
- Total simulation time: ~2-3 seconds wall time for 35 seconds simulated
- PDF generation: < 2 seconds

---

For detailed implementation notes, see `IMPLEMENTATION_GUIDE.md`.
