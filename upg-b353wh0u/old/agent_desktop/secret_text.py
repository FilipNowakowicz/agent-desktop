"""Hide text that looks like a generated credential before it leaves the worker.

Browser `find` and `wait` describe matching elements with their text, label and
value, and an agent needs them to choose the element it then passes to `send`.
A dialog that shows a new API token would otherwise put the token in the reply.
This is a heuristic for values shown once (API keys, access tokens, private
keys), not a guarantee: `send` remains the route for any secret.

A run of token characters is hidden when it
- starts with a known credential prefix (KNOWN), or
- has a separator-free part of at least RANDOM_LENGTH characters that mixes
  letters and digits at least RANDOM_SWITCHES times and has a Shannon entropy
  of at least RANDOM_ENTROPY bits per character, the way random base62/base64
  does and words, paths, version strings and CSS class names do not.

Pure hexadecimal parts, UUIDs and absolute paths are shown: commit ids, checksums, digests and
resource ids are what pages show most, and agents need to read them. A secret
written only in hex or as a UUID is therefore not hidden.
"""

import math
import re
from collections import Counter

# Credential prefixes, matched at the start of a token run.
KNOWN = re.compile(
    r"""(?x)
    (?: tskey-[A-Za-z0-9-]{8,}                  # Tailscale
      | (?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}  # GitHub
      | github_pat_[A-Za-z0-9_]{20,}
      | glpat-[A-Za-z0-9_-]{16,}                # GitLab
      | sk-[A-Za-z0-9_-]{16,}                   # OpenAI, Anthropic (sk-ant-)
      | [sr]k_(?:live|test)_[A-Za-z0-9]{10,}    # Stripe secret and restricted
      | xox[abposr]-[A-Za-z0-9-]{10,}           # Slack
      | (?:AKIA|ASIA)[0-9A-Z]{16}               # AWS access key id
      | AIza[0-9A-Za-z_-]{30,}                  # Google API key
      | ya29\.[0-9A-Za-z_-]{20,}                # Google OAuth access token
      | 1//0[0-9A-Za-z_-]{20,}                  # Google OAuth refresh token
      | npm_[A-Za-z0-9]{30,}                    # npm
      | pypi-[A-Za-z0-9_-]{30,}                 # PyPI
      | hf_[A-Za-z0-9]{30,}                     # Hugging Face
      | dop_v1_[a-f0-9]{30,}                    # DigitalOcean
      | SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}  # SendGrid
      | eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}    # JSON Web Token
    )"""
)
# Characters a generated token is written with; anything else ends a run.
RUN = re.compile(r"[A-Za-z0-9+/=_\-.~]+")
SEPARATORS = re.compile(r"[-_.~]")
HEX = re.compile(r"(?:0x)?[0-9a-fA-F]+")
UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

RANDOM_LENGTH = 20
RANDOM_SWITCHES = 3
RANDOM_ENTROPY = 3.5


def marker(length):
    return f"<hidden: looks like a secret, {length} chars; use send>"


def entropy(value):
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def random_part(part):
    """A separator-free part written like random base62/base64."""
    if len(part) < RANDOM_LENGTH or HEX.fullmatch(part):
        return False
    switches = sum(
        a.isdigit() != b.isdigit()
        for a, b in zip(part, part[1:], strict=False)
        if a.isalnum() and b.isalnum()
    )
    return switches >= RANDOM_SWITCHES and entropy(part) >= RANDOM_ENTROPY


def looks_secret(token):
    """Whether one run of token characters looks like a generated credential."""
    if KNOWN.match(token):
        return True
    # An absolute path's parts (a /nix/store hash) are names, not credentials.
    if len(token) < RANDOM_LENGTH or UUID.fullmatch(token) or token[0] == "/":
        return False
    return any(random_part(part) for part in SEPARATORS.split(token))


def hide(text):
    """The text with secret-looking runs replaced by a marker, and whether any was."""
    if not isinstance(text, str) or not text:
        return text, False
    if PRIVATE_KEY.search(text):
        return marker(len(text)), True
    hidden = False

    def replace(match):
        nonlocal hidden
        token = match.group()
        # A sentence's full stop or a trailing "=" pad is part of the run.
        core = token.rstrip(".")
        if not looks_secret(core):
            return token
        hidden = True
        return marker(len(core)) + token[len(core) :]

    return RUN.sub(replace, text), hidden


def cut(text, limit):
    """The first limit characters, keeping a marker that the cut would split."""
    if len(text) <= limit:
        return text
    start = text.rfind("<hidden: ", 0, limit)
    if start != -1:
        end = text.find(">", start)
        if end >= limit:
            return text[: end + 1]
    return text[:limit]


def shorten(text, limit):
    """At most limit characters, ending with an ellipsis when cut."""
    if len(text) <= limit:
        return text
    return cut(text, limit - 1).rstrip() + " …"


def hide_fields(item, fields, limit=None):
    """Hide secret-looking text in item's fields in place.

    Names of changed fields are listed under "hidden". With limit, each field
    is then cut to that many characters (after hiding, so a cut never leaves
    part of a secret that hiding would have recognised whole).
    """
    changed = []
    for field in fields:
        value = item.get(field)
        if isinstance(value, list):
            results = [hide(v) for v in value]
            item[field] = [v for v, _ in results]
            if any(h for _, h in results):
                changed.append(field)
            continue
        if not isinstance(value, str):
            continue
        value, was = hide(value)
        if limit is not None:
            value = cut(value, limit)
        item[field] = value
        if was:
            changed.append(field)
    if changed:
        item["hidden"] = sorted(set(item.get("hidden", [])) | set(changed))
    return item
