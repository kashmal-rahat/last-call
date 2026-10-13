"""Twilio for the phone demo (Module 9, D61/D62): one outbound call and WhatsApp messages,
always to the single number in the `phone-demo-config` secret.

Plain REST over httpx with API-key auth; no Twilio SDK needed for two endpoints.
Never logs or returns phone numbers, credentials or Twilio response bodies.
"""

from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, SecretStr, StringConstraints, ValidationError

from lastcall_shared.config import Settings
from lastcall_shared.ids import E164_PATTERN

TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}"

E164 = Annotated[str, StringConstraints(strip_whitespace=True, pattern=E164_PATTERN)]


class TwilioError(Exception):
    """Twilio is not configured, or refused a request. Messages never contain numbers or secrets."""


class PhoneDemoConfig(BaseModel):
    """The `phone-demo-config` secret. Created by hand; never stored in Terraform state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_sid: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^AC[0-9a-fA-F]{32}$")]
    api_key_sid: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^SK[0-9a-fA-F]{32}$")]
    api_key_secret: SecretStr
    from_number: E164  # the Twilio voice number
    to_number: E164  # the presenter's SIM: the only number calls and messages ever go to
    whatsapp_from: E164 | None = None  # the WhatsApp sender (sandbox: +14155238886); None = no WhatsApp


def load_phone_demo_config(settings: Settings) -> PhoneDemoConfig:
    raw = settings.PHONE_DEMO_CONFIG
    if raw is None:
        raise TwilioError("PHONE_DEMO_CONFIG is not set")
    try:
        return PhoneDemoConfig.model_validate_json(raw.get_secret_value())
    except ValidationError as exc:
        # Field names only: pydantic's message would echo the input (numbers, secret).
        fields = sorted({".".join(str(p) for p in err["loc"]) or "(json)" for err in exc.errors()})
        raise TwilioError(f"PHONE_DEMO_CONFIG is invalid: {', '.join(fields)}") from None


class TwilioClient:
    def __init__(
        self,
        config: PhoneDemoConfig,
        *,
        timeout_s: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests: httpx.MockTransport
    ) -> None:
        self._config = config
        self._timeout_s = timeout_s
        self._transport = transport

    @property
    def whatsapp_enabled(self) -> bool:
        return self._config.whatsapp_from is not None

    async def create_call(self, twiml: str, *, ring_seconds: int) -> None:
        """Rings the presenter's SIM and runs `twiml` once answered. Recording stays off (Twilio's default)."""
        await self._post(
            "Calls.json",
            {
                "To": self._config.to_number,
                "From": self._config.from_number,
                "Twiml": twiml,
                "Timeout": str(ring_seconds),
            },
        )

    async def send_whatsapp(self, body: str, *, media_url: str | None = None) -> None:
        """Sends a WhatsApp message to the presenter's SIM (needs an open 24 h session in the sandbox)."""
        if self._config.whatsapp_from is None:
            raise TwilioError("WhatsApp is not configured (whatsapp_from)")
        data = {
            "To": f"whatsapp:{self._config.to_number}",
            "From": f"whatsapp:{self._config.whatsapp_from}",
            "Body": body,
        }
        if media_url:
            data["MediaUrl"] = media_url
        await self._post("Messages.json", data)

    async def _post(self, resource: str, data: dict[str, str]) -> None:
        url = f"{TWILIO_API.format(account_sid=self._config.account_sid)}/{resource}"
        auth = (self._config.api_key_sid, self._config.api_key_secret.get_secret_value())
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client:
                resp = await client.post(url, auth=auth, data=data)
        except httpx.HTTPError as exc:
            raise TwilioError(f"Twilio {resource} request failed: {type(exc).__name__}") from None
        if resp.status_code >= 300:
            raise TwilioError(f"Twilio {resource} returned HTTP {resp.status_code}")
