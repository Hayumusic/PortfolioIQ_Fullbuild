# Portfolio IQ

Portfolio IQ analyzes an uploaded enterprise application inventory (CMDB) and its configured mandatory fields and output families. The application contains a FastAPI backend and a Next.js frontend.

## Run locally

Start the backend in one terminal:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. The backend health endpoint is `http://127.0.0.1:8000/health`.

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md) for API workflow, module details, and checks.
