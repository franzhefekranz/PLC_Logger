# SPDX-License-Identifier: LGPL-3.0-or-later
# Copyright (C) 2026 Michael Taxis
"""Benutzer und Passwörter des Webservers – ohne Flask (wird auch vom Konfigurationsprogramm verwendet).

Passwörter werden nur als Hash gespeichert: PBKDF2-HMAC-SHA256 mit zufälligem Salz und 600 000 Durchläufen, im
Format ``pbkdf2:sha256:600000$<Salz>$<Hash>`` (dasselbe Format wie werkzeug.security, also austauschbar).
"""
import hashlib
import hmac
import json
import secrets

ITERATIONS = 600_000


def hash_password(password, iterations=ITERATIONS):
    """Passwort -> Hash zum Speichern in der Konfiguration."""
    salt = secrets.token_urlsafe(12)[:16]
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations).hex()
    return f"pbkdf2:sha256:{iterations}${salt}${h}"


def check_password(stored, password):
    """Passt das Passwort zum gespeicherten Hash? (pbkdf2-Format; andere Formate über werkzeug, falls vorhanden)"""
    if not stored or not isinstance(stored, str):
        return False
    try:
        method, salt, h = stored.split("$", 2)
        parts = method.split(":")
        if parts[0] == "pbkdf2":
            algo = parts[1] if len(parts) > 1 else "sha256"
            it = int(parts[2]) if len(parts) > 2 else 600_000
            calc = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt.encode("utf-8"), it).hex()
            return hmac.compare_digest(calc, h)
    except (ValueError, TypeError):
        return False
    try:                                              # z. B. scrypt-Hashes von werkzeug
        from werkzeug.security import check_password_hash
        return check_password_hash(stored, password)
    except Exception:
        return False


def parse_users(text):
    """Einstellung web_benutzer (JSON {Name: Hash}) -> dict; ungültig/leer -> {}."""
    if isinstance(text, dict):
        return {str(k): str(v) for k, v in text.items() if k and v}
    try:
        d = json.loads(text or "{}")
        return {str(k): str(v) for k, v in d.items() if k and v} if isinstance(d, dict) else {}
    except ValueError:
        return {}
