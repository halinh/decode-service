import os

import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from jwt import PyJWKClient
from pydantic import BaseModel

load_dotenv()

# mock-oidc-provider signs id_tokens with RS256; fetch its public keys from the
# JWKS endpoint. PyJWKClient caches keys and refetches when it sees a new `kid`
# (e.g. after the provider restarts with a fresh key).
OIDC_JWKS_URL = os.environ.get("OIDC_JWKS_URL", "http://localhost:4000/jwks")
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "http://localhost:4000")

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/decode")
def decode_token(payload: DecodeRequest) -> dict:
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(payload.id_token)
        claims = jwt.decode(
            payload.id_token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=OIDC_ISSUER,
            # `aud` carries the client_id; this service is client-agnostic.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        # Covers signature/expiry/issuer failures and PyJWKClientError (a subclass).
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return claims
