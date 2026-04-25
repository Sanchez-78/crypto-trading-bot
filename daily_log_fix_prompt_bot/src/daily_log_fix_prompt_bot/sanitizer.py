"""Sanitize logs by redacting secrets."""

import re
import logging

log = logging.getLogger(__name__)


class Sanitizer:
    """Redact sensitive information from logs."""

    # Patterns to redact
    PATTERNS = [
        (r"[a-zA-Z0-9+/]{40,}={0,2}", "[REDACTED_KEY]"),  # API keys/tokens
        (r"AIzaSy[A-Za-z0-9_-]{35}", "[REDACTED_GOOGLE_KEY]"),  # Google API key
        (r"sk_[a-z0-9]{24,}", "[REDACTED_SK]"),  # Stripe keys
        (r"pk_[a-z0-9]{24,}", "[REDACTED_PK]"),  # Stripe public key
        (r"Bearer\s+[a-zA-Z0-9._-]+", "Bearer [REDACTED_TOKEN]"),  # Bearer tokens
        (r"password['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", "password=***"),  # Passwords
        (r"api_key['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", "api_key=***"),  # API keys
        (r"firebase_key['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", "firebase_key=***"),  # Firebase
        (r"secret['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", "secret=***"),  # Secrets
        (r"[0-9]{2,}\.{1}[0-9]{1,}\.[0-9]{1,3}\.[0-9]{1,3}", "[REDACTED_IP]"),  # IP addresses
    ]

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Redact sensitive information."""
        for pattern, replacement in cls.PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    @classmethod
    def sanitize_file(cls, filepath: str, output_filepath: str = None) -> str:
        """Sanitize a log file."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            sanitized = cls.sanitize(content)

            if output_filepath:
                with open(output_filepath, "w", encoding="utf-8") as f:
                    f.write(sanitized)
                log.info(f"Sanitized logs written to {output_filepath}")

            return sanitized
        except Exception as e:
            log.error(f"Failed to sanitize file: {e}")
            return ""
