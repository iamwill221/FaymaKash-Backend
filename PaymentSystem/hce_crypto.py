"""
Cryptographic utilities for HCE token generation/verification
and DESFire EV3 physical card CMAC verification.

Two authentication paths:
  - HCE:  HMAC-SHA256 signed tokens (phone emulation)
  - FK:   AES-CMAC verified tokens (DESFire EV3 physical cards)
"""

import base64
import hashlib
import hmac
import json
import struct
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HCE token (phone path)
# ---------------------------------------------------------------------------

@dataclass
class HCETokenPayload:
    user_id: int
    ts: int
    nonce: str


def generate_hce_token(user_id: int) -> str:
    """
    Generate an HMAC-SHA256 signed, single-use, time-limited token.
    Format: HCE:<base64_payload>.<signature_hex_16>
    """
    payload = {
        "uid": user_id,
        "ts": int(time.time()),
        "nonce": uuid.uuid4().hex,
    }
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()

    sig = hmac.new(
        settings.HCE_SECRET_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]

    return f"HCE:{payload_b64}.{sig}"


def verify_hce_token(token: str) -> HCETokenPayload:
    """
    Verify an HCE token's HMAC signature, expiration, and nonce uniqueness.
    Returns the decoded payload on success; raises ValueError on any failure.
    """
    from .models import UsedNonce

    if not token.startswith("HCE:"):
        raise ValueError("Format de token HCE invalide.")

    body = token[4:]
    parts = body.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError("Format de token HCE invalide.")

    payload_b64, sig_received = parts

    expected_sig = hmac.new(
        settings.HCE_SECRET_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]

    if not hmac.compare_digest(expected_sig, sig_received):
        raise ValueError("Signature HMAC invalide.")

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        raise ValueError("Payload du token HCE illisible.")

    ts = payload.get("ts", 0)
    lifetime = getattr(settings, "HCE_TOKEN_LIFETIME_SECONDS", 30)
    if abs(time.time() - ts) > lifetime:
        raise ValueError("Token HCE expiré.")

    nonce = payload.get("nonce", "")
    if not nonce:
        raise ValueError("Nonce manquant dans le token HCE.")

    if UsedNonce.is_used(nonce):
        raise ValueError("Token HCE déjà utilisé (rejeu détecté).")

    UsedNonce.mark_used(nonce)

    return HCETokenPayload(
        user_id=payload["uid"],
        ts=ts,
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# DESFire EV3 physical card CMAC verification (FK token path)
# ---------------------------------------------------------------------------

def _aes_cmac(key_bytes: bytes, message: bytes) -> bytes:
    """
    Compute AES-128 CMAC (RFC 4493).
    Uses PyCryptodome if available, otherwise falls back to a manual
    implementation using only the stdlib + basic AES.
    """
    try:
        from Crypto.Hash import CMAC
        from Crypto.Cipher import AES
        cobj = CMAC.new(key_bytes, ciphermod=AES)
        cobj.update(message)
        return cobj.digest()
    except ImportError:
        raise ImportError(
            "pycryptodome is required for card CMAC verification. "
            "Install it with: pip install pycryptodome"
        )


@dataclass
class FKVerificationResult:
    card_uid: str


def verify_fk_token(token: str, card_lookup) -> FKVerificationResult:
    """
    Verify a DESFire EV3 physical card CMAC token.

    Expected format: FK:<uid_hex_14>.<cmac_hex_16>

    card_lookup: callable(uid_hex) -> NFCCard  (raises DoesNotExist on failure)

    Steps:
      1. Parse UID and received CMAC from the token
      2. Look up the card and retrieve its read AES key
      3. Recompute AES-CMAC(readKey, uid_bytes), truncate with NXP method
      4. Constant-time compare
    """
    if not token.startswith("FK:"):
        raise ValueError("Format de token FK invalide.")

    body = token[3:]
    parts = body.split(".")
    if len(parts) != 2:
        raise ValueError("Format de token FK invalide (attendu: uid.cmac).")

    uid_hex, mac_hex = parts

    if len(uid_hex) != 14:
        raise ValueError("UID invalide (attendu: 7 octets / 14 hex).")
    if len(mac_hex) != 16:
        raise ValueError("CMAC invalide (attendu: 8 octets / 16 hex).")

    try:
        uid_bytes = bytes.fromhex(uid_hex)
        received_mac = bytes.fromhex(mac_hex)
    except ValueError:
        raise ValueError("Données FK mal formatées (hex invalide).")

    try:
        nfc_card = card_lookup(uid_hex)
    except Exception:
        raise ValueError("Carte physique inconnue.")

    if not nfc_card.sdm_aes_key:
        raise ValueError("Carte non configurée (clé AES manquante).")

    aes_key = bytes.fromhex(nfc_card.sdm_aes_key)

    # Recompute CMAC = AES-CMAC(readKey, uid_bytes) truncated to 8 bytes
    full_mac = _aes_cmac(aes_key, uid_bytes)
    # NXP truncation: take every other byte starting at index 1
    truncated_mac = bytes([full_mac[i] for i in range(1, 16, 2)])

    if not hmac.compare_digest(truncated_mac, received_mac):
        raise ValueError("CMAC invalide - carte potentiellement contrefaite.")

    nfc_card.last_accessed = __import__("django.utils.timezone", fromlist=["now"]).now()
    nfc_card.save(update_fields=["last_accessed"])

    return FKVerificationResult(card_uid=uid_hex)
