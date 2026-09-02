# decode-service

Minimal FastAPI service for the OIDC demo apps, alongside `mock-oidc-provider`:

- `POST /decode` — verifies an OIDC `id_token` (JWT, **RS256**) against
  `mock-oidc-provider`'s JWKS endpoint and returns its decoded claims as JSON.
  Used by `react-login`'s public flow and available standalone.
- `POST /token` — a **confidential token-exchange proxy** used by both
  `react-login`'s "confidential client via backend" flow and `next-login`'s
  `/callback`: it injects the `client_secret` server-side, forwards the
  `authorization_code` exchange to `mock-oidc-provider`, then decodes the
  returned `id_token` (same logic as `/decode`) and returns the tokens **plus**
  a `claims` object. The caller never sees the secret. Accepts a JSON body
  `{ "code", "code_verifier", "redirect_uri" }` (as sent by `request-oauth2`'s
  `exchangeCodeForTokenViaBackend`) or a form-urlencoded OAuth2 body. The
  confidential client is resolved from `redirect_uri` via `OIDC_TOKEN_CLIENTS`,
  so one running instance serves both demo apps.

## Run locally

```bash
cd /home/le-thi-ha-linh/Code/decode-service
uv sync
cp .env.example .env
uv run uvicorn main:app --reload --port 8000
```

`uv sync` creates `.venv` and installs the runtime deps plus the `dev`
dependency group (use `uv sync --no-dev` for runtime only).

The service listens on `http://localhost:8000`. `mock-oidc-provider` must be
running on `http://localhost:4000` so its JWKS can be fetched.

## Test

```bash
uv run pytest
```

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `OIDC_JWKS_URL` | `http://localhost:4000/jwks` | Where to fetch RSA public keys |
| `OIDC_ISSUER` | `http://localhost:4000` | Expected `iss` claim |
| `OIDC_TOKEN_URL` | `http://localhost:4000/token` | Upstream token endpoint for `POST /token` |
| `OIDC_CLIENT_ID` | `react-login-confidential` | Fallback confidential client id (when a `redirect_uri` is not in `OIDC_TOKEN_CLIENTS`) |
| `OIDC_CLIENT_SECRET` | `react-login-dev-secret-do-not-use-in-prod` | Fallback secret injected by `POST /token` (never leaves the server) |
| `OIDC_TOKEN_CLIENTS` | `{}` | JSON map `redirect_uri → { client_id, client_secret }`; lets one instance serve multiple confidential clients. See `.env.example`. |

## Routes

- `GET /health` — liveness check, returns `{"status": "ok"}`.
- `POST /decode` — body `{ "id_token": "<jwt>" }`. Verifies the JWT (RS256, key
  resolved by `kid` from `OIDC_JWKS_URL`, `iss` checked against `OIDC_ISSUER`,
  `aud` not checked) and returns the decoded claims as JSON. Returns `400` with
  `{"detail": "Invalid or expired token"}` for an invalid, tampered, or expired
  token, or one signed with any algorithm other than RS256. **Unchanged** — the
  verify/decode logic is now a `decode_id_token()` helper shared with `POST /token`.
- `POST /token` — confidential token-exchange proxy. Accepts either a JSON body
  `{ "code", "code_verifier", "redirect_uri" }` (as sent by `request-oauth2`'s
  `exchangeCodeForTokenViaBackend`) or an `application/x-www-form-urlencoded`
  `authorization_code` body (`grant_type`, `redirect_uri`, `code`,
  `code_verifier`). `grant_type` defaults to `authorization_code`; `client_id` +
  `client_secret` are resolved from `redirect_uri` (via `OIDC_TOKEN_CLIENTS`,
  falling back to `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET`) and forwarded to
  `OIDC_TOKEN_URL`. Missing `code` / `code_verifier` / `redirect_uri` → `400`. On
  success it also decodes the returned `id_token` and responds with the token
  JSON **plus** a `claims` object. An upstream OAuth2 error (e.g.
  `400 invalid_grant`, `401 invalid_client`) is passed through with its status;
  `502` if the exchange succeeds but the `id_token` is missing or fails
  verification.

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

### Confidential token exchange (`POST /token`)

Mint a code + verifier for `react-login-confidential`, then hand only the code to
the proxy — it adds the secret and returns tokens + decoded claims in one shot:

```bash
B=http://localhost:4000
V=$(node -e 'console.log(require("crypto").randomBytes(32).toString("base64url"))')
C=$(node -e "console.log(require('crypto').createHash('sha256').update('$V').digest('base64url'))")
LOC=$(curl -s -o /dev/null -D - -X POST "$B/authorize" \
  --data-urlencode "client_id=react-login-confidential" \
  --data-urlencode "redirect_uri=http://localhost:5173/callback" \
  --data-urlencode "scope=openid profile email" \
  --data-urlencode "state=xyz" --data-urlencode "code_challenge=$C" \
  --data-urlencode "code_challenge_method=S256" \
  --data-urlencode "email=demo.user@example.com" --data-urlencode "password=demo1234" \
  | grep -i '^location:' | tr -d '\r' | sed 's/^[Ll]ocation: //')
CODE=$(node -e "console.log(new URL('$LOC').searchParams.get('code'))")

curl -s -X POST http://localhost:8000/token \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=$CODE" \
  --data-urlencode "redirect_uri=http://localhost:5173/callback" \
  --data-urlencode "code_verifier=$V"
```

Or send the JSON body shape (what `exchangeCodeForTokenViaBackend` uses) — no
`grant_type`, no `client_id`:

```bash
curl -s -X POST http://localhost:8000/token \
  -H "Content-Type: application/json" \
  -d "{\"code\": \"$CODE\", \"code_verifier\": \"$V\", \"redirect_uri\": \"http://localhost:5173/callback\"}"
```

Expected: `200` with `access_token`, `id_token`, … **and** a `claims` object.
Dropping `code_verifier` makes `mock-oidc-provider` return `400 invalid_grant`
(PKCE is enforced for every client), which the proxy passes straight through.
Using `redirect_uri=http://localhost:3000/callback` resolves the
`next-login-confidential` client instead (see `OIDC_TOKEN_CLIENTS`).
