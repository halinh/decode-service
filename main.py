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

# Confidential token-exchange proxy config (POST /token). Lets react-login's
# browser run request-oauth2's exchangeCodeForToken normally while the
# client_secret stays server-side.
OIDC_TOKEN_URL = os.environ.get("OIDC_TOKEN_URL", "http://localhost:4000/token")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "react-login-confidential")
OIDC_CLIENT_SECRET = os.environ.get(
    "OIDC_CLIENT_SECRET", "react-login-dev-secret-do-not-use-in-prod"
)

_jwks_client = PyJWKClient(OIDC_JWKS_URL)

app = FastAPI(title="decode-service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
    """Confidential token-exchange proxy. Accepts the same form-urlencoded
    authorization_code body an OAuth2 token endpoint does (as sent by
    request-oauth2's exchangeCodeForToken), injects client_id + client_secret
    server-side, forwards to OIDC_TOKEN_URL, and on success also decodes the
    id_token (same logic as POST /decode). Returns the token response plus a
    `claims` object; passes an upstream OAuth2 error + status straight through."""
    # The body is always application/x-www-form-urlencoded (as sent by
    # exchangeCodeForToken); parse it directly to avoid a python-multipart dep.
    incoming = dict(parse_qsl((await request.body()).decode()))
    form = {
        **incoming,  # grant_type, redirect_uri, code, code_verifier
        "client_id": OIDC_CLIENT_ID,  # pin to the confidential client
        "client_secret": OIDC_CLIENT_SECRET,
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
