from urllib.parse import parse_qs

import httpx
import respx
from cryptography.hazmat.primitives.asymmetric import rsa

TOKEN_URL = "http://localhost:4000/token"


def _token_body(id_token):
    return {
        "access_token": "at-1",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "rt-1",
        "scope": "openid profile email",
        "id_token": id_token,
    }


def _authorization_code_form():
    return {
        "grant_type": "authorization_code",
        "client_id": "react-login-public",  # browser-sent value; proxy must override
        "redirect_uri": "http://localhost:5173/callback",
        "code": "auth-code-123",
        "code_verifier": "verifier-xyz",
    }


def _json_body(redirect_uri="http://localhost:5173/callback"):
    return {
        "code": "auth-code-123",
        "code_verifier": "verifier-xyz",
        "redirect_uri": redirect_uri,
    }


@respx.mock
def test_happy_path_exchanges_and_decodes(client, make_id_token, stub_jwks):
    stub_jwks()
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_token_body(make_id_token()))
    )

    r = client.post("/token", data=_authorization_code_form())

    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] == "at-1"
    assert body["claims"]["sub"] == "demo-user-1"

    forwarded = parse_qs(route.calls.last.request.content.decode())
    assert forwarded["client_secret"] == ["react-login-dev-secret-do-not-use-in-prod"]
    assert forwarded["client_id"] == ["react-login-confidential"]
    assert forwarded["code_verifier"] == ["verifier-xyz"]


@respx.mock
def test_upstream_invalid_grant_is_passed_through(client):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    r = client.post("/token", data=_authorization_code_form())

    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


@respx.mock
def test_upstream_invalid_client_is_passed_through(client):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )

    r = client.post("/token", data=_authorization_code_form())

    assert r.status_code == 401


@respx.mock
def test_id_token_signed_by_wrong_key_yields_502(client, make_id_token, stub_jwks):
    wrong_pub = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    stub_jwks(public_key=wrong_pub)
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_token_body(make_id_token()))
    )

    r = client.post("/token", data=_authorization_code_form())

    assert r.status_code == 502


@respx.mock
def test_missing_id_token_yields_502(client):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at-1"})
    )

    r = client.post("/token", data=_authorization_code_form())

    assert r.status_code == 502


@respx.mock
def test_json_body_exchanges_and_decodes(client, make_id_token, stub_jwks):
    stub_jwks()
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_token_body(make_id_token()))
    )

    r = client.post("/token", json=_json_body())

    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] == "at-1"
    assert body["claims"]["sub"] == "demo-user-1"

    forwarded = parse_qs(route.calls.last.request.content.decode())
    assert forwarded["grant_type"] == ["authorization_code"]
    assert forwarded["client_id"] == ["react-login-confidential"]
    assert forwarded["client_secret"] == ["react-login-dev-secret-do-not-use-in-prod"]
    assert forwarded["code_verifier"] == ["verifier-xyz"]


@respx.mock
def test_json_body_resolves_client_by_redirect_uri(client, make_id_token, stub_jwks):
    stub_jwks()
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_token_body(make_id_token()))
    )

    r = client.post("/token", json=_json_body("http://localhost:3000/callback"))

    assert r.status_code == 200
    forwarded = parse_qs(route.calls.last.request.content.decode())
    assert forwarded["client_id"] == ["next-login-confidential"]
    assert forwarded["client_secret"] == ["next-login-dev-secret-do-not-use-in-prod"]


def test_json_body_missing_field_yields_400(client):
    r = client.post(
        "/token",
        json={"code": "auth-code-123", "code_verifier": "verifier-xyz"},
    )

    assert r.status_code == 400
