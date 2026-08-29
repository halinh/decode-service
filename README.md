# decode-service

Minimal FastAPI service exposing `POST /decode`: verifies an OIDC `id_token`
(JWT, **RS256**) against `mock-oidc-provider`'s JWKS endpoint and returns its
decoded claims as JSON. Used by the `react-login` and `next-login` demo apps
alongside `mock-oidc-provider`.

## Run locally

```bash
cd /home/le-thi-ha-linh/Code/decode-service
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

The service listens on `http://localhost:8000`. `mock-oidc-provider` must be
running on `http://localhost:4000` so its JWKS can be fetched.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `OIDC_JWKS_URL` | `http://localhost:4000/jwks` | Where to fetch RSA public keys |
| `OIDC_ISSUER` | `http://localhost:4000` | Expected `iss` claim |

## Routes

- `GET /health` — liveness check, returns `{"status": "ok"}`.
- `POST /decode` — body `{ "id_token": "<jwt>" }`. Verifies the JWT (RS256, key
  resolved by `kid` from `OIDC_JWKS_URL`, `iss` checked against `OIDC_ISSUER`,
  `aud` not checked) and returns the decoded claims as JSON. Returns `400` with
  `{"detail": "Invalid or expired token"}` for an invalid, tampered, or expired
  token, or one signed with any algorithm other than RS256.

`PyJWKClient` caches keys and refetches when it sees a new `kid`, so a
`mock-oidc-provider` restart with a fresh key is picked up automatically.

## Manual end-to-end verification

Start `mock-oidc-provider` (port 4000) and this service (port 8000), then mint a
real `id_token` by completing the mock login flow:

```bash
B=http://localhost:4000
V=$(node -e 'console.log(require("crypto").randomBytes(32).toString("base64url"))')
C=$(node -e "console.log(require('crypto').createHash('sha256').update('$V').digest('base64url'))")
LOC=$(curl -s -o /dev/null -D - -X POST "$B/authorize" \
  --data-urlencode "client_id=react-login-public" \
  --data-urlencode "redirect_uri=http://localhost:5173/callback" \
  --data-urlencode "scope=openid profile email" \
  --data-urlencode "state=xyz" \
  --data-urlencode "code_challenge=$C" \
  --data-urlencode "code_challenge_method=S256" \
  | grep -i '^location:' | tr -d '\r' | sed 's/^[Ll]ocation: //')
CODE=$(node -e "console.log(new URL('$LOC').searchParams.get('code'))")
TOKEN=$(curl -s -X POST "$B/token" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=$CODE" \
  --data-urlencode "client_id=react-login-public" \
  --data-urlencode "redirect_uri=http://localhost:5173/callback" \
  --data-urlencode "code_verifier=$V" \
  | node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>console.log(JSON.parse(d).id_token))')
```

Decode it:

```bash
curl -s -X POST http://localhost:8000/decode \
  -H "Content-Type: application/json" \
  -d "{\"id_token\": \"$TOKEN\"}"
```

Expected: `200` with the decoded claims (`sub`, `iss`, `aud`, `azp`, `auth_time`,
`iat`, `exp`, plus `name`/`email`/… per the requested scope).

Tampered or wrong-algorithm tokens return `400`:

```bash
curl -s -X POST http://localhost:8000/decode \
  -H "Content-Type: application/json" \
  -d "{\"id_token\": \"${TOKEN}tampered\"}"
# {"detail":"Invalid or expired token"}
```
