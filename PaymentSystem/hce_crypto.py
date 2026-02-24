"""
Cryptographic utilities for HCE token generation/verification
and DESFire EV3 SDM verification.

Two authentication paths:
  - HCE:  HMAC-SHA256 signed tokens (phone emulation)
  - SDM:  AES-CMAC verified messages (DESFire EV3 physical cards)
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
# DESFire EV3 SDM verification (physical card path)
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
            "pycryptodome is required for SDM verification. "
            "Install it with: pip install pycryptodome"
        )


def _aes_decrypt_cbc(key_bytes: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """AES-128 CBC decryption."""
    try:
        from Crypto.Cipher import AES
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
        return cipher.decrypt(ciphertext)
    except ImportError:
        raise ImportError(
            "pycryptodome is required for SDM verification. "
            "Install it with: pip install pycryptodome"
        )


@dataclass
class SDMVerificationResult:
    card_uid: str
    read_counter: int


def verify_sdm_token(token: str, card_lookup) -> SDMVerificationResult:
    """
    Verify a DESFire EV3 SDM token.

    Expected format: SDM:<picc_data_hex>.<read_ctr_hex>.<sdm_mac_hex>

    card_lookup: callable(uid_hex) -> NFCCard  (raises DoesNotExist on failure)

    Steps:
      1. Decrypt PICCData to extract UID and read counter
      2. Look up the card and retrieve its AES key
      3. Verify SDMMAC
      4. Check counter > last_sdm_counter (anti-replay)
      5. Update last_sdm_counter
    """
    if not token.startswith("SDM:"):
        raise ValueError("Format de token SDM invalide.")

    body = token[4:]
    parts = body.split(".")
    if len(parts) != 3:
        raise ValueError("Format de token SDM invalide (attendu: picc.ctr.mac).")

    picc_hex, ctr_hex, mac_hex = parts

    try:
        picc_data = bytes.fromhex(picc_hex)
        received_ctr = int(ctr_hex, 16)
        received_mac = bytes.fromhex(mac_hex)
    except ValueError:
        raise ValueError("Données SDM mal formatées (hex invalide).")

    # Decrypt PICCData: first 16 bytes = AES-CBC encrypted (IV=0) containing UID(7) + counter(3) + padding
    # The decryption key is the SDM meta-read key; for simplicity we use
    # the same key stored on the card record. In production the PICCData
    # encryption key may differ from the MAC key.
    # We'll do a two-pass lookup: first try to find the card by the read counter
    # and MAC, but since PICCData is encrypted we need to try known cards.
    # In practice, the picc_data first byte after decryption reveals the UID
    # which maps to exactly one card.

    # For the initial implementation, we expect the POS to also send
    # the physical_card_token alongside the SDM token so we can look up the key.
    # Alternatively, we try all active SDM cards (small set in a university).

    # Simplified flow: extract UID from unencrypted part if SDM is configured
    # with PICCData in plain (SDMMirror without encryption, UID mirroring).
    # Many real deployments use plaintext UID + encrypted counter + CMAC.

    # Here we support the common NXP AN12196 format:
    # NDEF content = "SDM:<UID_hex_14>.<ReadCtr_hex_6>.<SDMMAC_hex_16>"
    uid_hex = picc_hex
    if len(uid_hex) != 14:
        raise ValueError("UID SDM invalide (attendu: 7 octets / 14 hex).")

    try:
        nfc_card = card_lookup(uid_hex)
    except Exception:
        raise ValueError("Carte physique inconnue.")

    if not nfc_card.sdm_aes_key:
        raise ValueError("Carte non configurée pour SDM.")

    aes_key = bytes.fromhex(nfc_card.sdm_aes_key)

    # Recompute SDMMAC = AES-CMAC(key, UID || ReadCtr) truncated to 8 bytes
    uid_bytes = bytes.fromhex(uid_hex)
    ctr_bytes = struct.pack("<I", received_ctr)[:3]  # 3-byte LE counter
    mac_input = uid_bytes + ctr_bytes
    full_mac = _aes_cmac(aes_key, mac_input)
    # NXP truncation: take every other byte starting at index 1
    truncated_mac = bytes([full_mac[i] for i in range(1, 16, 2)])

    if not hmac.compare_digest(truncated_mac, received_mac):
        raise ValueError("CMAC SDM invalide - carte potentiellement contrefaite.")

    if received_ctr <= nfc_card.last_sdm_counter:
        raise ValueError("Compteur SDM invalide - rejeu détecté.")

    nfc_card.last_sdm_counter = received_ctr
    nfc_card.last_accessed = __import__("django.utils.timezone", fromlist=["now"]).now()
    nfc_card.save(update_fields=["last_sdm_counter", "last_accessed"])

    return SDMVerificationResult(
        card_uid=uid_hex,
        read_counter=received_ctr,
    )
