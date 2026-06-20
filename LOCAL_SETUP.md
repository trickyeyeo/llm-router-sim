# Local Development Setup

Run the LLM Router demo locally without Docker.

## Prerequisites

✅ **Already done for you:**
- Python 3.14 with venv activated
- Node.js v22+ and npm installed
- All Python dependencies installed
- All Node.js dependencies installed

## Quick Start (Recommended)

Run both backend and frontend together:

```bash
./start_all.sh
```

Then open your browser to: **http://localhost:5173**

Press `Ctrl+C` to stop both services.

---

## Alternative: Run Services Separately

### Terminal 1: Backend

```bash
./start_backend.sh
```

**Output:**
```
🚀 Starting LLM Router Backend...
API will be available at http://localhost:8000
Health check: http://localhost:8000/health

Press Ctrl+C to stop
```

Verify it's running:
```bash
curl http://localhost:8000/health
```

Should return: `{"status":"ok"}`

### Terminal 2: Frontend

```bash
./start_frontend.sh
```

**Output:**
```
🎨 Starting LLM Router Frontend...
UI will be available at http://localhost:5173
```

Then open your browser to: **http://localhost:5173**

---

## Running the Demo

1. Go to http://localhost:5173
2. Adjust parameters with sliders:
   - Concurrent Sessions (1-20)
   - Turns Per Session (1-10)
3. Click "Run Simulation"
4. Watch real-time progress:
   - GPU utilization cards update every heartbeat
   - Progress bar and request counter
   - Charts animate as data arrives
5. View results:
   - Key metrics (capacity improvement, cost reduction)
   - Comparison charts (overlay visualization)
   - Expert accordion with detailed breakdown
6. Export to PDF:
   - Click "Download Results as PDF" after simulation completes

---

## Troubleshooting

### Backend won't start

**Error:** `ModuleNotFoundError: No module named 'simulator'`
- **Fix:** Make sure you're running from project root directory:
  ```bash
  cd /Users/csbell/Work/llm-router
  ./start_backend.sh
  ```

**Error:** `Address already in use`
- **Fix:** Port 8000 is in use. Kill the process:
  ```bash
  lsof -i :8000
  # Find the PID and kill it
  kill -9 <PID>
  ```

**Error:** `Pydantic/FastAPI import errors`
- **Fix:** Make sure venv is activated:
  ```bash
  source venv/bin/activate
  pip install -r requirements.txt
  ```

### Frontend won't start

**Error:** `npm: command not found`
- **Fix:** Node.js not installed. Install from https://nodejs.org/

**Error:** `Port 5173 already in use`
- **Fix:** Kill the process:
  ```bash
  lsof -i :5173
  kill -9 <PID>
  ```

**Error:** `Cannot find module` after npm install
- **Fix:** Reinstall dependencies:
  ```bash
  cd webapp/frontend
  rm -rf node_modules package-lock.json
  npm install
  ```

### Frontend can't connect to backend

**Error:** Connection refused when running simulation
- **Fix:** Make sure backend is running on port 8000:
  ```bash
  curl http://localhost:8000/health
  ```
- If backend isn't running, start it in another terminal:
  ```bash
  ./start_backend.sh
  ```

### Simulation takes forever or hangs

**Problem:** Simulation is very slow
- **Note:** This is expected! First run might take 30-60 seconds to run both simulations
- **Patience:** Let it complete; progress bar will update every second
- **Check logs:** Backend terminal will show activity

**Problem:** No progress updates
- **Check:** Make sure backend is logging events:
  ```
  # You should see output like:
  # heartbeat_data = {...}
  # final_data = {...}
  ```

### PDF export fails

**Error:** PDF download button doesn't work
- **Check browser console:** Open DevTools (F12) → Console
- **Try again:** Refresh page and re-run simulation
- **Note:** PDF generation takes a few seconds; be patient

---

## Development Workflow

### Hot Reload (Frontend)

Frontend supports hot reload automatically with Vite:
1. Edit files in `webapp/frontend/src/`
2. Save file
3. Browser updates automatically (no manual refresh needed)

### Backend Changes

Backend doesn't support hot reload:
1. Edit files in `webapp/main.py` or simulator code
2. Stop backend: `Ctrl+C`
3. Restart: `./start_backend.sh`

### Dependencies

**Add Python packages:**
```bash
source venv/bin/activate
pip install <package_name>
pip freeze > requirements.txt
```

**Add Node packages:**
```bash
cd webapp/frontend
npm install <package_name>
```

---

## Clean Up

### Clear Python cache

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete
```

### Clear Node cache

```bash
cd webapp/frontend
rm -rf node_modules .next dist build
npm cache clean --force
npm install
```

### Full reset

```bash
# Python
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Node
cd webapp/frontend
rm -rf node_modules package-lock.json
npm install
```

---

## Performance Tips

- **First run is slower:** Simulations compile/optimize on first run
- **Subsequent runs are faster:** Re-running same simulation is ~2-3x faster
- **Reduce parameters:** Use fewer sessions/turns for quick testing
- **Check CPU:** Watch Activity Monitor to see simulation progress

---

## Useful Commands

```bash
# Check Python version
python --version

# Check Node version  
node --version && npm --version

# Test backend health
curl http://localhost:8000/health

# Run simulation programmatically
curl "http://localhost:8000/simulate?num_sessions=3&turns_per_session=3"

# Check if ports are in use
lsof -i :8000  # Backend
lsof -i :5173  # Frontend

# View backend logs (while running)
# Check the terminal where you ran start_backend.sh

# View frontend logs
# Open browser DevTools: F12 → Console
```

---

## Need Help?

- **Backend issues:** Check terminal output where you ran `./start_backend.sh`
- **Frontend issues:** Open browser DevTools (F12) and check Console
- **Simulation issues:** Look at CLI output for error messages
- **Documentation:** See WEBAPP_README.md and webapp/IMPLEMENTATION_GUIDE.md
