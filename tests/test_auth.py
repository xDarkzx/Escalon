import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from escalon.auth import EntraTokenVerifier

TENANT = "11111111-2222-3333-4444-555555555555"
AUDIENCE = "api://escalon"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key=KEY, **overrides) -> str:
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": AUDIENCE,
        "exp": int(time.time()) + 600,
        "scp": "Helpdesk.Use",
        "preferred_username": "Sam.Taylor@Contoso.test",
        "oid": "user-object-id",
        "azp": "copilot-studio-client",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def verifier():
    return EntraTokenVerifier(TENANT, AUDIENCE, signing_key=lambda _: KEY.public_key())


async def test_valid_token_yields_user_identity(verifier):
    access = await verifier.verify_token(token())

    assert access is not None
    assert access.claims["preferred_username"] == "Sam.Taylor@Contoso.test"
    assert access.subject == "user-object-id"
    assert access.client_id == "copilot-studio-client"


@pytest.mark.parametrize(
    "bad",
    [
        {"aud": "api://some-other-app"},
        {"iss": "https://login.microsoftonline.com/another-tenant/v2.0"},
        {"exp": int(time.time()) - 10},
        {"scp": "User.Read"},
        {"preferred_username": None},
    ],
    ids=["wrong-audience", "wrong-tenant", "expired", "missing-scope", "no-user"],
)
async def test_invalid_tokens_are_rejected(verifier, bad):
    assert await verifier.verify_token(token(**bad)) is None


async def test_token_signed_by_another_key_is_rejected(verifier):
    assert await verifier.verify_token(token(key=OTHER_KEY)) is None


async def test_garbage_is_rejected(verifier):
    assert await verifier.verify_token("not-a-jwt") is None
