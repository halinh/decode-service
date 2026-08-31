def test_decode_returns_claims_for_a_valid_token(client, make_id_token, stub_jwks):
    stub_jwks()
    r = client.post("/decode", json={"id_token": make_id_token()})
    assert r.status_code == 200
    assert r.json()["sub"] == "demo-user-1"


def test_decode_rejects_a_tampered_token(client, make_id_token, stub_jwks):
    stub_jwks()
    r = client.post("/decode", json={"id_token": make_id_token() + "tamper"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid or expired token"
