# WebApp Implementation Guide

## Project Structure

```
llm-router/
├── webapp/
│   ├── main.py                          # FastAPI backend
│   ├── Dockerfile.backend               # Backend container
│   ├── backend_requirements.txt         # Python dependencies
│   ├── docker-compose.yml               # Orchestration
│   └── frontend/
│       ├── package.json
│       ├── tsconfig.json
│       ├── vite.config.ts
│       ├── Dockerfile
│       ├── index.html
│       └── src/
│           ├── main.tsx                 # Entry point
│           ├── App.tsx                  # Main component
│           ├── components/
│           │   ├── ParameterPanel.tsx
│           │   ├── ProgressIndicator.tsx
│           │   ├── GPUCards.tsx
│           │   ├── KeyMetrics.tsx
│           │   ├── ComparisonCharts.tsx
│           │   └── ExpertAccordion.tsx
│           ├── hooks/
│           │   └── useSimulation.ts
│           └── utils/
│               └── pdfExport.ts
├── simulator/                           # Existing simulation code
├── router/                              # Existing router code
└── [other existing files]
```

## Implementation Checklist

### Phase 1: Backend Setup ✓
- [x] Create `webapp/main.py` with FastAPI app
- [x] Create `webapp/backend_requirements.txt`
- [x] Create `webapp/Dockerfile.backend`
- [ ] Test backend locally: `python webapp/main.py`

### Phase 2: Frontend Setup
- [ ] Create `webapp/frontend/` directory structure
- [ ] Create `webapp/frontend/package.json`
- [ ] Create `webapp/frontend/tsconfig.json`
- [ ] Create `webapp/frontend/vite.config.ts`
- [ ] Create `webapp/frontend/Dockerfile`
- [ ] Create `webapp/frontend/index.html`
- [ ] Create `webapp/frontend/src/main.tsx`

### Phase 3: React Components
- [ ] `App.tsx` - Main container
- [ ] `components/ParameterPanel.tsx` - Slider controls ✓
- [ ] `components/ProgressIndicator.tsx` - Progress bar
- [ ] `components/GPUCards.tsx` - Live GPU status
- [ ] `components/KeyMetrics.tsx` - Hero metrics
- [ ] `components/ComparisonCharts.tsx` - Overlay charts
- [ ] `components/ExpertAccordion.tsx` - Detailed breakdown

### Phase 4: Hooks & Utils
- [ ] `hooks/useSimulation.ts` - SSE event handling
- [ ] `utils/pdfExport.ts` - PDF generation

### Phase 5: Docker & Deployment
- [ ] Update `docker-compose.yml`
- [ ] Create `webapp/frontend/Dockerfile`
- [ ] Test with `docker-compose up`

## Key Files Created So Far

1. ✅ `webapp/main.py` - FastAPI backend with `/simulate` endpoint
2. ✅ `webapp/backend_requirements.txt` - Backend dependencies
3. ✅ `webapp/Dockerfile.backend` - Backend container
4. ✅ `webapp/components_ParameterPanel.tsx` - Parameter controls
5. ✅ `webapp/docker-compose.yml` - Docker orchestration

## Files Still Needed

### Frontend Files
1. `webapp/frontend/package.json`
2. `webapp/frontend/tsconfig.json`
3. `webapp/frontend/vite.config.ts`
4. `webapp/frontend/index.html`
5. `webapp/frontend/Dockerfile`
6. `webapp/frontend/src/main.tsx`
7. `webapp/frontend/src/App.tsx`
8. `webapp/frontend/src/components/*.tsx`
9. `webapp/frontend/src/hooks/useSimulation.ts`
10. `webapp/frontend/src/utils/pdfExport.ts`
11. `webapp/frontend/public/index.css` (Tailwind)

## Data Flow

### Backend → Frontend (SSE Stream)

**Heartbeat Event:**
```json
{
  "type": "heartbeat",
  "progress": 0.45,
  "current_time_ms": 15750,
  "total_time_ms": 35000,
  "stateless": {
    "gpus": {
      "gpu0": {
        "hbm_utilization": 0.95,
        "cache_hit_rate": 0.0,
        "num_cached_blocks": 0,
        "active_requests": 8
      },
      "gpu1": {...}
    },
    "requests": {
      "generated": 120,
      "completed": 95
    }
  },
  "stateful": {
    "gpus": {...},
    "requests": {...}
  }
}
```

**Complete Event:**
```json
{
  "type": "complete",
  "stateless": {...full metrics...},
  "stateful": {...full metrics...}
}
```

## Component Specifications

### ParameterPanel
- 2 range sliders (sessions: 1-20, turns: 1-10)
- "Run Simulation" button
- Display estimate of total requests
- Disable controls while running ✓

### ProgressIndicator
- Visual progress bar (0-100%)
- Current time / Total time display
- Request counter (completed / generated)
- For both stateless and stateful

### GPUCards (Side-by-side comparison)
- 2x GPU cards for each routing strategy (stateless + stateful)
- Show: HBM %, cache hit %, blocks, active requests
- Smooth animations for value changes
- Color: green <50%, yellow 50-80%, red >80%

### KeyMetrics
- Large display numbers:
  - Capacity improvement: `ceil(stateful_capacity / stateless_capacity)`x
  - Cost reduction %
  - Cache hit rate %
  - Avg TTFT ms
- Update as simulation completes

### ComparisonCharts
- Use Recharts with overlay (red stateless, green stateful)
- 4 charts:
  1. TTFT per turn (line chart)
  2. HBM utilization over time (area chart)
  3. Cache hit rate progression (line chart)
  4. Throughput (bar chart)

### ExpertAccordion (Auto-open)
- Section 1: Per-turn metrics table
- Section 2: Routing strategy breakdown
- Section 3: Per-GPU detailed metrics
- Section 4: Key findings summary

## Color Scheme

- **Stateless:** Gray / Red
  - Neutral: `#6B7280` (gray-500)
  - Alert: `#EF4444` (red-500)

- **Stateful:** Green / Blue
  - Success: `#22C55E` (green-500)
  - Info: `#3B82F6` (blue-500)

## Next Steps

1. Create frontend directory structure
2. Set up Vite + React + TypeScript
3. Build components one by one
4. Wire up SSE event handling
5. Test with Docker Compose
6. Add PDF export functionality
