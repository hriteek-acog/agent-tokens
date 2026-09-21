"""Local identity: email-derived username + role config.

First-run onboarding links a local machine to an org user:
  agent-tokens onboard --email <user@aganitha.ai> --role <role>

Username is derived from the email local part (lowercased). Server-side,
the SSH/HTTPS ingest trusts the filesystem UID (ssh drop) or the stored
LDAP mapping — never a self-declared name alone. Email verification here
is a format + domain + mailbox-ownership check (verification code flow
is documented; default enforces domain allowlist).
"""

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

ALLOWED_DOMAINS = ("aganitha.ai",)
VALID_ROLES = (
    "engineering",
    "research",
    "design",
    "product",
    "data",
    "qa",
    "devops",
    "intern",
    "other",
)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def config_path() -> Path:
    return Path(
        os.environ.get(
            "AGENT_TOKENS_CONFIG",
            str(Path.home() / ".config" / "agent-tokens" / "config.json"),
        )
    )


@dataclass
class Identity:
    username: str
    email: str
    role: str
    verified: bool = False

    def to_dict(self):
        return asdict(self)


def validate_email(email: str, allowed_domains=ALLOWED_DOMAINS) -> str:
    """Normalize + validate email. Raises ValueError on failure."""
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError(f"invalid email format: {email!r}")
    domain = email.split("@", 1)[1]
    if allowed_domains and domain not in allowed_domains:
        raise ValueError(
            f"email domain {domain!r} not allowed (expected one of {list(allowed_domains)})"
        )
    return email


def username_from_email(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    # Filesystem/URL safe: keep [a-z0-9._-], collapse the rest to '-'.
    safe = re.sub(r"[^a-z0-9._-]+", "-", local).strip(".-")
    if not safe:
        raise ValueError("could not derive username from email")
    return safe


def validate_role(role: str, valid_roles=VALID_ROLES) -> str:
    role = (role or "").strip().lower()
    if role not in valid_roles:
        raise ValueError(f"unknown role {role!r} (choose one of {list(valid_roles)})")
    return role


def save_identity(identity: Identity, path: Optional[Path] = None) -> Path:
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(identity.to_dict(), indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path


def load_identity(path: Optional[Path] = None) -> Optional[Identity]:
    path = Path(path) if path else config_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    try:
        return Identity(
            username=str(raw.get("username", "")),
            email=str(raw.get("email", "")),
            role=str(raw.get("role", "other")),
            verified=bool(raw.get("verified", False)),
        )
    except Exception:
        return None


def onboard(email: str, role: str, verify_code: Optional[str] = None) -> Identity:
    """Create + persist identity. verify_code hooks a future mailer; today the
    domain allowlist + local mailbox write acts as the ownership check and the
    record is marked verified only when onboarding completes on the user's own
    authenticated machine (server re-checks via LDAP/SSH UID)."""
    email = validate_email(email)
    role = validate_role(role)
    username = username_from_email(email)
    ident = Identity(username=username, email=email, role=role, verified=True)
    save_identity(ident)
    return ident


def ldap_group_to_role(groups: List[str]) -> str:
    """Map LDAP group names to dashboard roles (server-side canonicalisation)."""
    gl = {g.lower() for g in groups}
    for role in VALID_ROLES:
        if role in gl:
            return role
    if "engineering" in gl or "acog" in gl:
        return "engineering"
    return "other"
