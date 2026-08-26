# decode-service

Minimal FastAPI service exposing `POST /decode`: verifies an OIDC `id_token`
(JWT, HS256) against a shared dev secret and returns its decoded claims as
JSON. Used by the `react-login` and `next-login` demo apps alongside
`mock-oidc-provider`.

## Run locally

```bash
cd /home/le-thi-ha-linh/Code/decode-service
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env   # already present in this repo with the shared dev secret
uvicorn main:app --reload --port 8000
```

The service listens on `http://localhost:8000`.

## Routes

- `GET /health` — liveness check, returns `{"status": "ok"}`.
- `POST /decode` — body `{ "id_token": "<jwt>" }`. Verifies the JWT against
  `JWT_DEV_SECRET` (HS256) and returns the decoded claims as JSON. Returns
  `400` with `{"detail": "Invalid or expired token"}` for an invalid,
  tampered, or expired token.

## Manual end-to-end verification

See the "Manual end-to-end verification" section below (added once the
`/decode` route and CORS are implemented).
