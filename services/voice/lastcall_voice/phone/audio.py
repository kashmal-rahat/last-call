"""Telephone audio conversion for the phone demo (Module 9).

Twilio Media Streams carry 8 kHz mu-law (G.711). The Live session takes 16 kHz PCM16
in and returns 24 kHz PCM16 out. Pure Python: audioop is deprecated in 3.12 and removed
in 3.13, and a few thousand samples per second need no native code.
"""

import sys
from array import array

_BIAS = 0x84
_CLIP = 32635


def _ulaw_to_linear(u: int) -> int:
    u = ~u & 0xFF
    sign = u & 0x80
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    sample = (((mantissa << 3) + _BIAS) << exponent) - _BIAS
    return -sample if sign else sample


def _linear_to_ulaw(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    if sample < 0:
        sample = -sample
    sample = min(sample, _CLIP) + _BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not sample & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (sample >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


_DECODE = array("h", [_ulaw_to_linear(i) for i in range(256)])
_ENCODE = bytes(_linear_to_ulaw(s - 32768) for s in range(65536))  # index: sample + 32768
_SWAP = sys.byteorder != "little"  # PCM on the wire is little-endian


def _to_bytes(samples: array) -> bytes:
    if _SWAP:
        samples.byteswap()
    return samples.tobytes()


def _from_bytes(data: bytes) -> array:
    samples = array("h")
    samples.frombytes(data)
    if _SWAP:
        samples.byteswap()
    return samples


class InboundConverter:
    """Twilio 8 kHz mu-law -> 16 kHz PCM16 (linear interpolation, state kept across frames)."""

    def __init__(self) -> None:
        self._prev = 0

    def convert(self, mulaw: bytes) -> bytes:
        out = array("h")
        prev = self._prev
        for byte in mulaw:
            sample = _DECODE[byte]
            out.append((prev + sample) // 2)
            out.append(sample)
            prev = sample
        self._prev = prev
        return _to_bytes(out)


class OutboundConverter:
    """Live 24 kHz PCM16 -> Twilio 8 kHz mu-law.

    Averages each group of 3 samples before keeping one (a simple low-pass, so speech
    above 4 kHz doesn't fold back as hiss). Leftover bytes carry over to the next chunk.
    """

    def __init__(self) -> None:
        self._carry = b""

    def convert(self, pcm: bytes) -> bytes:
        data = self._carry + pcm
        usable = (len(data) // 6) * 6  # 3 samples x 2 bytes
        self._carry = data[usable:]
        samples = _from_bytes(data[:usable])
        out = bytearray(len(samples) // 3)
        for j in range(len(out)):
            k = 3 * j
            out[j] = _ENCODE[(samples[k] + samples[k + 1] + samples[k + 2]) // 3 + 32768]
        return bytes(out)
