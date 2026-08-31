import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import main

TOKEN_URL = "http://localhost:4000/token"
ISSUER = "http://localhost:4000"


@pytest.fixture(scope="session")
def rsa_keys():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


@pytest.fixture
def make_id_token(rsa_keys):
    priv, _ = rsa_keys

    def _make(**overrides):
        now = int(time.time())
        claims = {
            "sub": "demo-user-1",
            "iss": ISSUER,
            "aud": "react-login-confidential",
            "iat": now,
            "exp": now + 3600,
            "name": "Demo User",
            "email": "demo.user@example.com",
        }
        claims.update(overrides)
        return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": "test-key"})

    return _make


@pytest.fixture
def stub_jwks(monkeypatch, rsa_keys):
    """PyJWKClient fetches JWKS with urllib, not httpx, so respx can't intercept
    it — patch the signing-key lookup on the module singleton instead."""
    _, default_pub = rsa_keys

    def _use(public_key=None):
        key = default_pub if public_key is None else public_key
        monkeypatch.setattr(
            main._jwks_client,
            "get_signing_key_from_jwt",
            lambda _token: SimpleNamespace(key=key),
        )

    return _use


@pytest.fixture
def client():
    return TestClient(main.app)
