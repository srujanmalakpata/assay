from __future__ import annotations

import pytest

from sut.security import hash_password, new_token, verify_password

pytestmark = pytest.mark.unit


def test_hash_round_trip() -> None:
    stored = hash_password("s3cret-password")
    assert stored.startswith("pbkdf2_sha256$")
    assert "s3cret-password" not in stored
    assert verify_password("s3cret-password", stored)
    assert not verify_password("wrong-password", stored)


def test_same_password_gets_different_salts() -> None:
    assert hash_password("same-password") != hash_password("same-password")


@pytest.mark.parametrize("garbage", ["", "plain", "md5$1$aa$bb", "a$b$c"])
def test_malformed_hashes_never_verify(garbage: str) -> None:
    assert verify_password("anything", garbage) is False


def test_tokens_are_long_and_unique() -> None:
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) >= 40 for t in tokens)
