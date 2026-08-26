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

Start the server:

```bash
cd /home/le-thi-ha-linh/Code/decode-service
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

In another terminal, mint a valid HS256 JWT signed with the same
`JWT_DEV_SECRET` this service verifies against (this stands in for the
`id_token` that `mock-oidc-provider` issues):

```bash
TOKEN=$(python3 -c "
import jwt, time
secret = 'dev-only-insecure-shared-secret-do-not-use-in-prod'
payload = {
    'sub': 'demo-user-123',
    'email': 'demo@example.com',
    'name': 'Demo User',
    'iat': int(time.time()),
    'exp': int(time.time()) + 3600,
}
print(jwt.encode(payload, secret, algorithm='HS256'))
")
echo "$TOKEN"
```

Decode it:

```bash
curl -s -X POST http://localhost:8000/decode \
  -H "Content-Type: application/json" \
  -d "{\"id_token\": \"$TOKEN\"}"
```

Expected response (`200`, `iat`/`exp` reflect the actual run time):

```json
{"sub":"demo-user-123","email":"demo@example.com","name":"Demo User","iat":1798500000,"exp":1798503600}
```

Try a tampered token:

```bash
curl -s -X POST http://localhost:8000/decode \
  -H "Content-Type: application/json" \
  -d "{\"id_token\": \"${TOKEN}tampered\"}"
```

Expected response (`400`):

```json
{"detail":"Invalid or expired token"}
```

Try an expired token:

```bash
EXPIRED_TOKEN=$(python3 -c "
import jwt, time
secret = 'dev-only-insecure-shared-secret-do-not-use-in-prod'
payload = {
    'sub': 'demo-user-123',
    'iat': int(time.time()) - 7200,
    'exp': int(time.time()) - 3600,
}
print(jwt.encode(payload, secret, algorithm='HS256'))
")

curl -s -X POST http://localhost:8000/decode \
  -H "Content-Type: application/json" \
  -d "{\"id_token\": \"$EXPIRED_TOKEN\"}"
```

Expected response (`400`):

```json
{"detail":"Invalid or expired token"}
```
