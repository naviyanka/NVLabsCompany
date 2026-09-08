"""Secret scanning for vault writes (ADR 0002 §20 control 7).

A write that persists a credential into a Git-tracked file is not undone by
deleting the line: the secret stays in history, and history is the vault's whole
version story (§18). So the scan happens *before* bytes reach the filesystem, and
a positive match refuses the write rather than redacting it — redaction would
write a file the author did not intend and still leave the original in whatever
buffer produced it.

Fail closed. Three outcomes, and only one of them permits a write:

``clean``
    Nothing matched. The write may proceed.
``secret_detected``
    A pattern or a high-entropy token matched. The write is refused.
``scanner_error``
    The scan could not complete — undecodable bytes, a pathological input, an
    unexpected failure. The write is refused, because "we could not check" is not
    "there is nothing there".

**No detection library is installed.** The declared dependencies carry no
``detect-secrets``, ``trufflehog`` or equivalent, and adding one for a
frontmatter stamp is a heavier bet than the job needs. What is here is a small
pattern set plus a Shannon-entropy check on assignment-shaped values, which is
the same shape those tools use for their generic rules.

Limitations, stated rather than implied:

- **Patterns only catch known shapes.** A bespoke internal token format with no
  recognisable prefix and moderate entropy passes.
- **Entropy is a heuristic.** It runs only on values that look assigned
  (``key: value``, ``key=value``) and above a length floor, so a long
  base64-encoded diagram or a UUID-dense note can produce a false positive. That
  is the intended direction of error for a write path.
- **No Git history scan.** This checks the bytes about to be written, not what is
  already committed.
- **No cross-line reasoning.** A credential split over two lines is not detected.
- **Vault notes are prose.** Refusing a legitimate note that quotes a fake key is
  an acceptable cost; the author can rephrase. Writing a real key is not.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Scan outcomes.
SCAN_CLEAN = "clean"
SCAN_SECRET_DETECTED = "secret_detected"
SCAN_SCANNER_ERROR = "scanner_error"

# Above this many bytes the input is not a note anybody wrote by hand. Scanning
# it would be a denial-of-service surface on the write path, and refusing is the
# fail-closed answer.
MAX_SCAN_BYTES = 2_000_000

# Entropy floor for an assigned value. 4.0 bits/char sits above English prose
# (~2.5) and ordinary identifiers, and below base64-encoded random material
# (~5.5-6.0).
ENTROPY_THRESHOLD = 4.0

# Shortest assigned value considered for the entropy check. Below this, entropy
# is statistically meaningless and every hex colour would match.
MIN_ENTROPY_LENGTH = 24

# Named credential shapes. Each name is what a refusal reports — the matched text
# is never echoed, because a refusal reason is logged and returned to a caller.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b")),
    ("stripe_secret_key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "bearer_token",
        re.compile(r"\b[Aa]uthorization\s*[:=]\s*[\"']?Bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    ),
    (
        "database_url_with_password",
        # A URL carrying inline credentials: scheme://user:secret@host
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s:/@]{6,}@[^\s/]+"),
    ),
    (
        "assigned_password",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
            r"client[_-]?secret|private[_-]?key)\b\s*[:=]\s*[\"']?(?!\s)"
            r"[^\s\"',]{8,}"
        ),
    ),
)

# Values that look assigned, for the entropy pass. The key is not restricted:
# a bespoke token under an unremarkable name is exactly what patterns miss.
_ASSIGNMENT = re.compile(r"[A-Za-z0-9_.\-]{2,}\s*[:=]\s*[\"']?([A-Za-z0-9+/_=-]{%d,})" % MIN_ENTROPY_LENGTH)

# Assigned values that are structurally not secrets. Checked before entropy so a
# note full of ids does not become unwritable.
_ENTROPY_ALLOWLIST = (
    # A UUID — every obsidian_documents id, and every id a note's frontmatter
    # legitimately carries.
    re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
    # An ISO-8601 timestamp.
    re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"),
    # A hex digest — a content hash, not a credential.
    re.compile(r"(?i)^[0-9a-f]{32,128}$"),
)


@dataclass(frozen=True)
class SecretScanResult:
    """What a scan concluded.

    Attributes:
        outcome: One of ``clean``, ``secret_detected``, ``scanner_error``.
        findings: Names of what matched — rule names and line numbers only. The
            matched text is deliberately absent: a result is logged and returned
            to a caller, so putting the secret in it would defeat the scan.
        detail: A short client-safe explanation, for a ``scanner_error``.
    """

    outcome: str
    findings: tuple[str, ...] = field(default_factory=tuple)
    detail: str = ""

    @property
    def allowed(self) -> bool:
        """Whether a write may proceed. Only a clean scan permits one."""
        return self.outcome == SCAN_CLEAN


def shannon_entropy(text: str) -> float:
    """Bits of entropy per character, for a non-empty string."""
    if not text:
        return 0.0
    counts = Counter(text)
    length = len(text)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def scan_text(text: str) -> SecretScanResult:
    """Scan note text for credential material.

    Args:
        text: The full note content about to be written, frontmatter included —
            a credential is no less exposed for sitting in a YAML key.

    Returns:
        A :class:`SecretScanResult`. Never raises: an unexpected failure becomes
        ``scanner_error``, which refuses the write, because a scanner that throws
        must not be the reason a secret gets written.
    """
    try:
        if len(text.encode("utf-8", errors="surrogatepass")) > MAX_SCAN_BYTES:
            return SecretScanResult(
                outcome=SCAN_SCANNER_ERROR,
                detail="Content is too large to scan for credentials.",
            )

        findings: list[str] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in _PATTERNS:
                if pattern.search(line):
                    findings.append(f"{name}:line {lineno}")

            for match in _ASSIGNMENT.finditer(line):
                value = match.group(1)
                if any(allowed.match(value) for allowed in _ENTROPY_ALLOWLIST):
                    continue
                if shannon_entropy(value) >= ENTROPY_THRESHOLD:
                    findings.append(f"high_entropy_value:line {lineno}")

        if findings:
            # Deduplicated and ordered, so the same rule firing twice on one line
            # reads as one finding.
            return SecretScanResult(
                outcome=SCAN_SECRET_DETECTED, findings=tuple(dict.fromkeys(findings))
            )
        return SecretScanResult(outcome=SCAN_CLEAN)
    except Exception as exc:  # noqa: BLE001 - a scanner failure must fail closed
        logger.exception("Secret scan failed; refusing the write")
        return SecretScanResult(
            outcome=SCAN_SCANNER_ERROR, detail=f"Scan failed: {type(exc).__name__}"
        )


def scan_bytes(content: bytes) -> SecretScanResult:
    """Scan raw bytes destined for a note file.

    Bytes rather than text is the writer's real boundary, and undecodable bytes
    are their own answer: a vault note is UTF-8 Markdown, so content that is not
    decodable is not a note, and it cannot be scanned. That is a
    ``scanner_error``, which refuses the write.

    Args:
        content: The exact bytes that would be written.

    Returns:
        A :class:`SecretScanResult`.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return SecretScanResult(
            outcome=SCAN_SCANNER_ERROR,
            detail="Content is not valid UTF-8, so it cannot be scanned.",
        )
    return scan_text(text)
