"""D62: signed item-photo links; D61/D62: the phone-demo Twilio config and client."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

from lastcall_shared.config import Settings
from lastcall_shared.item_photos import sign_item_photo_url, verify_item_photo_signature
from lastcall_shared.twilio import PhoneDemoConfig, TwilioClient, TwilioError, load_phone_demo_config

KEY = "test-signing-key-12345-at-least-32-chars-long"
NOW = 1_800_000_000.0
TO_NUMBER = "+923001234567"  # fictional
CONFIG = {
    "account_sid": "AC" + "a" * 32,
    "api_key_sid": "SK" + "b" * 32,
    "api_key_secret": "test-secret",
    "from_number": "+15550001111",
    "to_number": TO_NUMBER,
    "whatsapp_from": "+14155238886",
}


# --- Signed photo links --------------------------------------------------------------


def _parts(url: str) -> tuple[str, int, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return parsed.path, int(query["exp"][0]), query["sig"][0]


def test_signed_link_verifies_for_its_item_until_it_expires():
    url = sign_item_photo_url("https://api.example.com/", "insp_1", "banana_top", key=KEY, now=NOW, ttl_s=60)
    path, exp, sig = _parts(url)
    assert url.startswith("https://api.example.com/demo/item-photos/insp_1/banana_top.jpg?")
    assert path == "/demo/item-photos/insp_1/banana_top.jpg"
    assert verify_item_photo_signature("insp_1", "banana_top", exp, sig, key=KEY, now=NOW)
    assert not verify_item_photo_signature("insp_1", "banana_top", exp, sig, key=KEY, now=NOW + 61)  # expired
    assert not verify_item_photo_signature("insp_1", "apple_center", exp, sig, key=KEY, now=NOW)  # other item
    assert not verify_item_photo_signature("insp_1", "banana_top", exp + 3600, sig, key=KEY, now=NOW)  # longer life
    assert not verify_item_photo_signature("insp_1", "banana_top", exp, sig, key=KEY + "x", now=NOW)  # other key


def test_signing_needs_a_key():
    with pytest.raises(ValueError):
        sign_item_photo_url("https://api.example.com", "insp_1", "banana_top", key=" ")


# --- Phone demo config -----------------------------------------------------------------


def _settings(config: dict | None) -> Settings:
    return Settings(
        APP_SIGNING_KEY=SecretStr(KEY),
        PHONE_DEMO_CONFIG=SecretStr(json.dumps(config)) if config is not None else None,
    )


def test_config_loads_and_whatsapp_is_optional():
    cfg = load_phone_demo_config(_settings(CONFIG))
    assert cfg.to_number == TO_NUMBER and cfg.whatsapp_from == "+14155238886"
    without_whatsapp = {k: v for k, v in CONFIG.items() if k != "whatsapp_from"}
    assert not TwilioClient(load_phone_demo_config(_settings(without_whatsapp))).whatsapp_enabled


@pytest.mark.parametrize(
    "config, field",
    [
        (None, "not set"),
        ({**CONFIG, "to_number": "0300 1234567"}, "to_number"),
        ({**CONFIG, "account_sid": "XX123"}, "account_sid"),
        ({**CONFIG, "surprise": 1}, "surprise"),
    ],
)
def test_bad_config_names_fields_without_echoing_values(config, field):
    with pytest.raises(TwilioError) as exc:
        load_phone_demo_config(_settings(config))
    assert field in str(exc.value)
    assert "1234567" not in str(exc.value) and "test-secret" not in str(exc.value)


# --- Twilio client ---------------------------------------------------------------------


def _client(status_code: int = 201) -> tuple[TwilioClient, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status_code, json={"sid": "XX", "to": TO_NUMBER})

    return TwilioClient(PhoneDemoConfig(**CONFIG), transport=httpx.MockTransport(handler)), sent


def _form(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


async def test_create_call_rings_the_configured_number():
    client, sent = _client()
    await client.create_call("<Response/>", ring_seconds=30)
    assert sent[0].url.path.endswith(f"/Accounts/{CONFIG['account_sid']}/Calls.json")
    assert sent[0].headers["authorization"].startswith("Basic ")
    assert _form(sent[0]) == {"To": TO_NUMBER, "From": "+15550001111", "Twiml": "<Response/>", "Timeout": "30"}


async def test_send_whatsapp_uses_whatsapp_addresses_and_media():
    client, sent = _client()
    await client.send_whatsapp("Deal confirmed", media_url="https://api.example.com/p.jpg")
    assert sent[0].url.path.endswith("/Messages.json")
    assert _form(sent[0]) == {
        "To": f"whatsapp:{TO_NUMBER}",
        "From": "whatsapp:+14155238886",
        "Body": "Deal confirmed",
        "MediaUrl": "https://api.example.com/p.jpg",
    }


async def test_twilio_errors_carry_status_only():
    client, _ = _client(status_code=400)
    with pytest.raises(TwilioError) as exc:
        await client.send_whatsapp("hi")
    assert str(exc.value) == "Twilio Messages.json returned HTTP 400"


async def test_whatsapp_needs_a_sender():
    cfg = PhoneDemoConfig(**{k: v for k, v in CONFIG.items() if k != "whatsapp_from"})
    with pytest.raises(TwilioError):
        await TwilioClient(cfg).send_whatsapp("hi")
