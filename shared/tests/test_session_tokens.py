"""Tests for short-lived HMAC session tokens (Milestone 2B Step 9)."""

import time
from datetime import datetime, timezone
import pytest

from lastcall_shared.session_tokens import mint, verify


def test_token_mint_and_verify_valid():
    key = "super-secret-key-12345"
    call_id = "call_abc_123"
    nonce = "nonce_xyz_789"

    token = mint(call_id=call_id, nonce=nonce, key=key, ttl=120)
    assert isinstance(token, str)
    assert "." in token

    valid, payload, err = verify(token, key=key)
    assert valid is True
    assert err is None
    assert payload is not None
    assert payload["call_id"] == call_id
    assert payload["nonce"] == nonce
    assert "exp" in payload


def test_token_expired():
    key = "super-secret-key-12345"
    call_id = "call_abc_123"
    nonce = "nonce_xyz_789"

    # Mint with ttl = 0 or negative
    token = mint(call_id=call_id, nonce=nonce, key=key, ttl=-10)
    valid, payload, err = verify(token, key=key)
    assert valid is False
    assert err == "Token expired"
    assert payload is not None
    assert payload["call_id"] == call_id


def test_token_tampered_payload():
    key = "super-secret-key-12345"
    token = mint(call_id="call_1", nonce="nonce_1", key=key, ttl=120)
    p_b64, sig_b64 = token.split(".")

    # Tamper with the payload string
    tampered_p_b64 = p_b64[:-2] + "AA"
    tampered_token = f"{tampered_p_b64}.{sig_b64}"

    valid, payload, err = verify(tampered_token, key=key)
    assert valid is False
    assert err == "Invalid signature"


def test_token_tampered_signature():
    key = "super-secret-key-12345"
    token = mint(call_id="call_1", nonce="nonce_1", key=key, ttl=120)
    p_b64, sig_b64 = token.split(".")

    tampered_sig = sig_b64[:-2] + ("bb" if sig_b64[-2:] != "bb" else "aa")
    tampered_token = f"{p_b64}.{tampered_sig}"

    valid, payload, err = verify(tampered_token, key=key)
    assert valid is False
    assert err == "Invalid signature"


def test_token_wrong_key():
    token = mint(call_id="call_1", nonce="nonce_1", key="key_one", ttl=120)
    valid, payload, err = verify(token, key="key_two")
    assert valid is False
    assert err == "Invalid signature"


def test_token_malformed():
    key = "super-secret-key"
    assert verify("invalid_no_dot", key)[0] is False
    assert verify("a.b.c", key)[0] is False
    assert verify(".sig", key)[0] is False


def test_token_mint_empty_key_raises():
    with pytest.raises(ValueError, match="cannot be empty"):
        mint(call_id="call_1", nonce="nonce_1", key="")

    with pytest.raises(ValueError, match="cannot be empty"):
        mint(call_id="call_1", nonce="nonce_1", key="   ")


def test_token_verify_empty_key_raises():
    token = mint(call_id="call_1", nonce="nonce_1", key="test-signing-key-12345", ttl=120)
    with pytest.raises(ValueError, match="cannot be empty"):
        verify(token, key="")

    with pytest.raises(ValueError, match="cannot be empty"):
        verify(token, key="   ")
