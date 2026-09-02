import json
import os
from urllib.parse import parse_qsl

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from jwt import PyJWKClient
from pydantic import BaseModel

load_dotenv()

# mock-oidc-provider signs id_tokens with RS256; fetch its public keys from the
# JWKS endpoint. PyJWKClient caches keys and refetches when it sees a new `kid`
# (e.g. after the provider restarts with a fresh key).
OIDC_JWKS_URL = os.environ.get("OIDC_JWKS_URL", "http://localhost:4000/jwks")
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "http://localhost:4000")

# Confidential token-exchange proxy config (POST /token). Lets a browser SPA
# (react-login) or a server route (next-login) run the authorization_code
# exchange without ever holding the client_secret — it stays here.
OIDC_TOKEN_URL = os.environ.get("OIDC_TOKEN_URL", "http://localhost:4000/token")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "react-login-confidential")
OIDC_CLIENT_SECRET = os.environ.get(
    "OIDC_CLIENT_SECRET", "react-login-dev-secret-do-not-use-in-prod"
)

# Optional multi-client registry so one running instance can serve more than one
# confidential client. JSON object keyed by redirect_uri:
#   {"http://localhost:5173/callback": {"client_id": "...", "client_secret": "..."}}
# The incoming request carries no client_id (the payload is just code +
# code_verifier + redirect_uri), so the client is resolved by redirect_uri.
# Falls back to OIDC_CLIENT_ID / OIDC_CLIENT_SECRET when a redirect_uri is not
# registered (or the registry is unset).
_CLIENT_REGISTRY: dict[str, dict[str, str]] = json.loads(
    os.environ.get("OIDC_TOKEN_CLIENTS", "{}")
)


def _resolve_client(redirect_uri: str | None) -> tuple[str, str]:
    entry = _CLIENT_REGISTRY.get(redirect_uri or "")
    if entry:
        return entry["client_id"], entry["client_secret"]
    return OIDC_CLIENT_ID, OIDC_CLIENT_SECRET

_jwks_client = PyJWKClient(OIDC_JWKS_URL)

app = FastAPI(title="decode-service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DecodeRequest(BaseModel):
    id_token: str


def decode_id_token(id_token: str) -> dict:
    """Verify an OIDC id_token (RS256, key by `kid` from the JWKS) and return its
    claims. Raises HTTPException(400) on any signature/expiry/issuer failure.
    Shared by POST /decode and the POST /token proxy."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(id_token)
        return jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=OIDC_ISSUER,
            # `aud` carries the client_id; this service is client-agnostic.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        # Covers signature/expiry/issuer failures and PyJWKClientError (a subclass).
        raise HTTPException(status_code=400, detail="Invalid or expired token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/decode")
def decode_token(payload: DecodeRequest) -> dict:
    return decode_id_token(payload.id_token)


@app.post("/token")
async def confidential_token(request: Request) -> Response:
    """Confidential token-exchange proxy. Injects client_id + client_secret
    server-side, forwards the authorization_code grant to OIDC_TOKEN_URL, and on
    success also decodes the id_token (same logic as POST /decode). Returns the
    token response plus a `claims` object; passes an upstream OAuth2 error +
    status straight through.

    Accepts two body shapes:
      - application/json: {"code", "code_verifier", "redirect_uri"} — as sent by
        request-oauth2's exchangeCodeForTokenViaBackend. No grant_type/client_id.
      - application/x-www-form-urlencoded: the full authorization_code body an
        OAuth2 token endpoint takes — as sent by request-oauth2's plain
        exchangeCodeForToken pointed here.
    The confidential client is resolved from redirect_uri (see _CLIENT_REGISTRY)."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            incoming = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="Malformed JSON body")
    else:
        # Parsed directly to avoid a python-multipart dependency.
        incoming = dict(parse_qsl((await request.body()).decode()))

    if not isinstance(incoming, dict) or not all(
        incoming.get(k) for k in ("code", "code_verifier", "redirect_uri")
    ):
        raise HTTPException(
            status_code=400,
            detail="code, code_verifier and redirect_uri are required",
        )

    client_id, client_secret = _resolve_client(incoming.get("redirect_uri"))
    form = {
        "grant_type": incoming.get("grant_type", "authorization_code"),
        "code": incoming["code"],
        "code_verifier": incoming["code_verifier"],
        "redirect_uri": incoming["redirect_uri"],
        "client_id": client_id,  # pinned server-side, ignoring any inbound value
        "client_secret": client_secret,
    }

    async with httpx.AsyncClient(timeout=10) as http:
        upstream = await http.post(OIDC_TOKEN_URL, data=form)

    if upstream.status_code != 200:
        # Pass the mock's OAuth2 error + status straight through, so
        # exchangeCodeForToken raises TokenExchangeError just as it would
        # against the real token endpoint.
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    tokens = upstream.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=502, detail="Upstream token response had no id_token")
    try:
        claims = decode_id_token(id_token)
    except HTTPException:
        raise HTTPException(status_code=502, detail="Issued id_token failed verification")

    return JSONResponse({**tokens, "claims": claims})
