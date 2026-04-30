"""Fill missing translations in Lingui .po catalogs (and science YAML files) via Azure AI Foundry.

Minimal-maintenance translation pipeline: English source text is authored in
the source code (extracted by `lingui extract` into `src/locales/en/messages.po`),
this script diff-reads the target-language catalog and fills any entries with
an empty `msgstr` using an Azure AI Foundry deployment. The output is a
PR-ready `.po` that a human reviews before merging.

Usage:
    # Fill missing zh translations in the .po catalog
    python scripts/translate_missing.py po \
        --source web/src/locales/en/messages.po \
        --target web/src/locales/zh/messages.po \
        --language "Simplified Chinese"

    # Translate every science YAML that lacks a zh counterpart
    python scripts/translate_missing.py yaml \
        --source-dir data/science \
        --target-dir data/science/zh \
        --language "Simplified Chinese"

Environment:
    AZURE_AI_ENDPOINT         Azure OpenAI resource base, e.g.
                              https://<resource>.cognitiveservices.azure.com/
    TRANSLATE_MODEL           Deployment name (default: gpt-5.4-mini). Must
                              match the "Name" column in Foundry Deployments.
    AZURE_OPENAI_API_VERSION  API version (default: 2025-04-01-preview).

Auth uses DefaultAzureCredential — in CI this resolves through OIDC federation
set up by `azure/login@v2`; locally it picks up `az login` or a dev workload
identity. No API key needed.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from openai import AzureOpenAI  # type: ignore[import-not-found]
    from azure.identity import (  # type: ignore[import-not-found]
        DefaultAzureCredential,
        get_bearer_token_provider,
    )
except ImportError:
    AzureOpenAI = None  # handled in _client()
    DefaultAzureCredential = None
    get_bearer_token_provider = None

MODEL = os.environ.get("TRANSLATE_MODEL", "gpt-5.4-mini")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")

# Lingui XML tag references (the numbered variant — <0>, </0>, <1/>). These
# must appear verbatim in every translation because Lingui compiles them
# back into React children at runtime.
_XML_TAG_RE = re.compile(r"</?\d+(?:\s*/)?>")


def _icu_variable_names(s: str) -> list[str]:
    """Walk `s` and extract the variable names of every *outermost* ICU
    placeholder. Handles nested braces in plural/select branches:

        "{count, plural, one {# item} other {# items}}"  ->  ["count"]
        "Hello {name}, you have {count} runs"           ->  ["name", "count"]
        "{count, plural, other {# 项}}"                 ->  ["count"]

    The comparison is on variable names only — branch contents (`# item` vs
    `# items` vs `# 项`) are allowed to differ, which is the whole point of
    translating plural branches.
    """
    names: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] != "{":
            i += 1
            continue
        # Balance-match braces to find the end of the outer placeholder.
        depth = 1
        j = i + 1
        while j < n and depth > 0:
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
            j += 1
        if depth != 0:
            # Unbalanced — treat the rest as literal, bail.
            break
        # `{` at i, matching `}` at j-1. Content is s[i+1 : j-1].
        inner = s[i + 1 : j - 1]
        # Variable name is everything before the first comma (or the whole
        # thing for a simple {name} placeholder).
        head = inner.split(",", 1)[0].strip()
        names.append(head)
        i = j
    return names


def _placeholders(s: str) -> dict[str, list[str]]:
    """Return the token fingerprint used for placeholder validation.

    Two keys:
      - `icu`:  sorted list of outermost ICU variable names
      - `xml`:  sorted list of Lingui XML tag references (<0>, </0>, <1/>)
    """
    return {
        "icu": sorted(_icu_variable_names(s)),
        "xml": sorted(_XML_TAG_RE.findall(s)),
    }


# ---------------------------------------------------------------------------
# .po file parsing (minimal — enough for Lingui's format)
# ---------------------------------------------------------------------------

def parse_po(path: Path) -> tuple[list[dict], list[str]]:
    """Parse a .po file into (entries, trailing_lines).

    `prefix_lines` on each entry captures comments (#: ...) and blank lines
    *preceding* its msgid. `trailing_lines` is anything after the last msgid
    — typically a trailing `#~` obsolete-entry block that Lingui puts at the
    file end. Preserving it is necessary for clean round-trips; discarding
    it drops translations for strings that might later be resurrected.
    """
    entries: list[dict] = []
    buf: list[str] = []  # comment / blank lines accumulated since the last msgid

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\n")
        stripped = raw.strip()
        if stripped.startswith("msgid "):
            msgid = _read_po_string(lines, i, "msgid ")
            i = _skip_continuation(lines, i)
            # Skip stray comment/blank lines between msgid and msgstr (rare
            # but legal in .po files we don't generate ourselves).
            while i < len(lines) and not lines[i].startswith("msgstr "):
                i += 1
            if i < len(lines):
                msgstr = _read_po_string(lines, i, "msgstr ")
                i = _skip_continuation(lines, i)
            else:
                msgstr = ""
            entries.append({
                "prefix_lines": buf,
                "msgid": msgid,
                "msgstr": msgstr,
            })
            buf = []
            continue
        buf.append(raw)
        i += 1

    return entries, buf


def _obsolete_block_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Return (start, end_exclusive) ranges for each obsolete entry block.

    A block is one or more contiguous `#~` lines plus the `#:` / `#.` / `#,`
    comment lines Lingui emits directly above them (which reference the
    now-obsolete msgid, not the following active entry). Blank lines are
    boundaries and never part of a block.
    """
    ranges: list[tuple[int, int]] = []
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].lstrip().startswith("#~"):
            # Walk back to collect refs/comments belonging to this obsolete
            # entry, stopping at a blank line or any non-`#` content.
            start = i
            j = i - 1
            while j >= 0:
                s = lines[j].lstrip()
                if s == "" or not s.startswith("#"):
                    break
                start = j
                j -= 1
            # Walk forward across contiguous `#~` lines.
            end = i
            while end < n and lines[end].lstrip().startswith("#~"):
                end += 1
            ranges.append((start, end))
            i = end
        else:
            i += 1
    return ranges


def _strip_obsolete(prefix_lines: list[str]) -> list[str]:
    """Remove entire obsolete-entry blocks (source refs + comments + `#~`
    lines) from a prefix block. Dropping only the `#~` lines would leave
    the preceding `#:` refs orphaned — they'd attach to the next active
    msgid on the next round-trip and point at files where the string was
    once referenced but no longer is.
    """
    if not prefix_lines:
        return prefix_lines
    kill = set()
    for start, end in _obsolete_block_ranges(prefix_lines):
        kill.update(range(start, end))
    return [ln for i, ln in enumerate(prefix_lines) if i not in kill]


def _extract_obsolete_blocks(
    entries: list[dict], trailing: list[str]
) -> list[str]:
    """Collect every obsolete-entry block (`#:` / `#.` refs + `#~` lines)
    from both inline prefixes and the trailing buffer. Used to preserve the
    target catalog's obsolete content — source-side blocks are irrelevant.
    Blocks are separated by a single blank line in the output.
    """
    out: list[str] = []

    def _append(lines: list[str]) -> None:
        for start, end in _obsolete_block_ranges(lines):
            if out:
                out.append("")
            out.extend(lines[start:end])

    for e in entries:
        _append(e["prefix_lines"])
    _append(trailing)
    return out


def _read_po_string(lines: list[str], idx: int, prefix: str) -> str:
    """Read a multiline quoted string from .po starting at prefix, following continuation lines."""
    assert lines[idx].lstrip().startswith(prefix)
    rest = lines[idx].lstrip()[len(prefix):].strip()
    parts = [_unquote(rest)]
    j = idx + 1
    while j < len(lines):
        nxt = lines[j].strip()
        if nxt.startswith('"') and nxt.endswith('"'):
            parts.append(_unquote(nxt))
            j += 1
            continue
        break
    return "".join(parts)


def _skip_continuation(lines: list[str], idx: int) -> int:
    """Return the index after a msgid/msgstr and its continuation lines."""
    j = idx + 1
    while j < len(lines):
        nxt = lines[j].strip()
        if nxt.startswith('"') and nxt.endswith('"'):
            j += 1
            continue
        return j
    return j


_PO_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}


def _unquote(s: str) -> str:
    """Strip the surrounding quotes from a .po string literal and resolve the
    handful of escape sequences Lingui emits (\\n, \\t, \\r, \\", \\\\).

    We walk character-by-character rather than routing through
    `unicode_escape`, which reinterprets UTF-8 continuation bytes as Latin-1
    and mangles every CJK character on round-trip.
    """
    if not (s.startswith('"') and s.endswith('"')):
        return s
    inner = s[1:-1]
    out: list[str] = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            out.append(_PO_ESCAPES.get(nxt, nxt))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _emit_po_string(key: str, value: str) -> list[str]:
    """Render a key/value as one or more .po output lines.

    If `value` contains embedded newlines (the PO header is the only common
    case in Lingui-generated catalogs), write the canonical multi-line
    continuation form Lingui emits:

        msgstr ""
        "line 1\\n"
        "line 2\\n"

    Single-line with `\\n` escapes is valid PO and parses identically, but
    Lingui rewrites it on every extract — producing pure diff noise. Keep
    round-trips boringly stable.
    """
    if "\n" not in value:
        return [f"{key} {_quote(value)}"]
    parts = value.split("\n")
    out = [f'{key} ""']
    for i, seg in enumerate(parts):
        if i < len(parts) - 1:
            out.append(_quote(seg + "\n"))
        elif seg != "":
            out.append(_quote(seg))
    return out


def write_po(path: Path, entries: list[dict], tail: list[str] | None = None) -> None:
    """Write entries back in .po format. The leading blank/comment block
    between entries lives in `prefix_lines`, so we emit no extra trailing
    newline after msgstr — otherwise every round-trip doubles the separators.

    `tail` holds any `#~` obsolete-entry block preserved from the target's
    original file; it's appended verbatim after the last active entry.
    """
    out: list[str] = []
    for e in entries:
        out.extend(e["prefix_lines"])
        out.extend(_emit_po_string("msgid", e["msgid"]))
        out.extend(_emit_po_string("msgstr", e["msgstr"]))
    if tail:
        out.extend(tail)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Translation via Claude
# ---------------------------------------------------------------------------

def _client():
    # Delegate to the shared factory in api.llm so both translation and
    # insight generation use the same auth scaffolding. The CLI exits hard
    # when the client is unavailable; the insight generator returns None
    # and the app falls back to rule-based prose.
    from api import llm as _llm

    client = _llm.get_client()
    if client is None:
        if AzureOpenAI is None:
            print(
                "openai / azure-identity not installed. "
                "Run: pip install openai azure-identity",
                file=sys.stderr,
            )
        else:
            print(
                "AZURE_AI_ENDPOINT is not set — point it at the Azure OpenAI "
                "resource base (e.g. https://<resource>.cognitiveservices.azure.com/).",
                file=sys.stderr,
            )
        sys.exit(2)
    return client


def _complete(client, system: str, user: str, max_tokens: int = 4096) -> str:
    """Single entry point for chat completions so the SDK surface lives in one place.

    Uses `max_completion_tokens` (not `max_tokens`) because GPT-5 and o-series
    deployments reject the deprecated argument name.
    """
    resp = client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


SYSTEM_PROMPT_BASE = """You translate UI strings for Praxys, a sports-science training platform
for endurance athletes. Rules:

1. Preserve every ICU/MessageFormat placeholder ({name}, {count, plural,
   one {#} other {#}}, {0}) and every Lingui XML tag (<0>...</0>, <1/>)
   VERBATIM. Count them in source and output — if the source has 2, the
   output must have 2. Do not rename, reorder, or drop them.
2. When translating to Simplified Chinese, pluralization collapses to a
   single `other` branch. Example source:
     "{count, plural, one {# item} other {# items}}"
   Example zh output:
     "{count, plural, other {# 项目}}"
3. Keep technical acronyms unchanged: HRV, TSB, CTL, ATL, CP, FTP, VO2max,
   RSS, rTSS, TRIMP, LTHR, km, W, bpm, /km, /mi.
4. Do not translate brand names: Praxys, Garmin, Stryd, Oura.
5. Match the source's punctuation style (ellipses, quote marks, whitespace
   around punctuation).
6. Output the translation ONLY — no prefix, no quotes, no explanation.
"""


def _glossary_section() -> str:
    """Read scripts/i18n_glossary.yaml and format it as a prompt appendix.

    Failing softly (file missing / PyYAML missing) keeps the translator
    usable in minimal environments; the terminology pinning is best-effort.
    """
    path = Path(__file__).with_name("i18n_glossary.yaml")
    if not path.exists():
        return ""
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return ""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ""
    terms = data.get("terms") or []
    lines = []
    for t in terms:
        en = t.get("en", "").strip()
        zh = t.get("zh", "").strip()
        note = t.get("note", "").strip()
        if not en:
            continue
        # Rows with empty zh signal "keep English" — emit that rule explicitly.
        rhs = zh if zh else "(keep English)"
        lines.append(f"- {en} → {rhs}" + (f" ({note})" if note else ""))
    if not lines:
        return ""
    return (
        "\n\nUse this glossary for Simplified Chinese. These renderings are "
        "canonical — reuse them exactly so terminology stays consistent across "
        "releases:\n" + "\n".join(lines)
    )


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_BASE + _glossary_section()


def _load_glossary() -> dict[str, str]:
    """Return {en: zh} for glossary rows with non-empty zh. Used to warn when
    a draft translation omits a canonical term from the glossary. Rows with
    empty zh ("keep English") are skipped — there's nothing to check.
    """
    path = Path(__file__).with_name("i18n_glossary.yaml")
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    out: dict[str, str] = {}
    for t in data.get("terms") or []:
        en = (t.get("en") or "").strip()
        zh = (t.get("zh") or "").strip()
        if en and zh:
            out[en] = zh
    return out


def _extract_context(prefix_lines: list[str]) -> tuple[list[str], list[str]]:
    """Pull .po metadata lines for prompt context.
    Returns (source_refs, extractor_comments) — `#: file:line` refs and `#. dev notes`.
    """
    sources: list[str] = []
    comments: list[str] = []
    for line in prefix_lines:
        s = line.strip()
        if s.startswith("#:"):
            sources.append(s[2:].strip())
        elif s.startswith("#."):
            comments.append(s[2:].strip())
    return sources, comments


def _format_entry_for_prompt(idx: int, entry: dict) -> str:
    """Render one entry as `N. <msgid>` plus an optional `(context ...)` line.

    Context is squeezed into a single parenthetical so response parsing can
    still rely on the `N.` prefix to locate translations.
    """
    text = f"{idx}. {entry['msgid']}"
    sources, comments = _extract_context(entry["prefix_lines"])
    parts: list[str] = []
    if comments:
        parts.append("note: " + "; ".join(comments))
    if sources:
        # First source ref is typically enough (GoalPage.tsx:142) to place the string.
        parts.append("at: " + sources[0])
    if not parts:
        return text
    return f"{text}\n   (context — {'; '.join(parts)})"


_NUMBERED_LINE_RE = re.compile(r"^\s*(\d+)\.\s*(.*)$")


def _parse_numbered_response(text: str, expected: int) -> list[str]:
    """Parse a numbered `N. translation` response into a list of length `expected`.

    Resilient to multi-line translations and interleaved model commentary:
    associates any line without an `N.` prefix with the last-seen number.
    Missing numbers become empty strings (the caller treats empties as "retry
    next run").
    """
    buckets: dict[int, list[str]] = {}
    current: int | None = None
    for line in text.splitlines():
        m = _NUMBERED_LINE_RE.match(line)
        if m:
            current = int(m.group(1))
            buckets.setdefault(current, []).append(m.group(2))
        elif current is not None:
            buckets[current].append(line)
    return [" ".join(buckets.get(i + 1, [])).strip() for i in range(expected)]


def _glossary_warnings(source: str, translation: str, glossary: dict[str, str]) -> list[str]:
    """Return a list of 'en → zh missing' warnings for glossary terms that
    appear in `source` but whose canonical `zh` rendering is absent from
    `translation`. Best-effort heuristic: case-insensitive substring match on
    the English side (so "Critical Power" matches "critical power"), exact
    substring match on the zh side.

    Intentionally warning-only, not rejection: Chinese renders many terms
    inflectionally ("Threshold Pace" → "阈值配速" without the noun), and we
    don't want to block legitimate translations on a noisy heuristic. Humans
    see the warnings in the PR log and fix the few that matter.
    """
    warnings: list[str] = []
    low = source.lower()
    for en, zh in glossary.items():
        if en.lower() in low and zh not in translation:
            warnings.append(f"{en!r} → missing {zh!r}")
    return warnings


def _placeholders_match(source: str, translation: str) -> bool:
    """True iff `translation` preserves every placeholder in `source`.

    ICU plural/select shapes may legitimately change between locales
    (en has `one` + `other`, zh collapses to `other` only), so we compare
    *variable names* rather than the full placeholder text. XML tag refs
    must match exactly because Lingui uses them as React-children indices.
    """
    return _placeholders(source) == _placeholders(translation)


def translate_batch(
    entries: list[dict],
    language: str,
    batch_size: int = 20,
    max_translations: int | None = None,
) -> dict[str, int]:
    """Translate entries whose msgstr is empty; mutates entries in place.

    Returns a summary dict with `filled`, `rejected_placeholder_mismatch`,
    and `capped` counts so the caller can surface them in CI logs.

    `max_translations`: hard ceiling on how many entries we attempt per run
    (cost safety). When the cap is hit, remaining entries stay empty and
    the CI PR will only refresh a subset — the next CI run picks up the
    rest. Set via env var `TRANSLATE_MAX` in the workflow.
    """
    missing = [e for e in entries if not e["msgstr"]]
    if not missing:
        print("No missing translations.", file=sys.stderr)
        return {"filled": 0, "rejected_placeholder_mismatch": 0, "glossary_warnings": 0, "capped": 0}

    capped = 0
    if max_translations is not None and len(missing) > max_translations:
        capped = len(missing) - max_translations
        missing = missing[:max_translations]
        print(
            f"Capping to {max_translations} translations this run "
            f"({capped} will remain empty for the next run).",
            file=sys.stderr,
        )

    client = _client()
    system_prompt = build_system_prompt()
    glossary = _load_glossary()
    print(f"Translating {len(missing)} entries to {language}...", file=sys.stderr)

    filled = 0
    rejected = 0
    glossary_warned = 0
    for start in range(0, len(missing), batch_size):
        chunk = missing[start:start + batch_size]
        numbered = "\n".join(
            _format_entry_for_prompt(i + 1, e) for i, e in enumerate(chunk)
        )
        user_prompt = (
            f"Translate these UI strings to {language}. "
            f"Each entry may include a `(context — ...)` line with the source "
            f"file and/or a developer note — use it to disambiguate (e.g. "
            f"'Save' as a button vs. as a noun) but DO NOT echo it in your "
            f"output. Output the translation only, one line per entry, "
            f"numbered 1., 2., 3., etc., in the same order. No commentary:"
            f"\n\n{numbered}"
        )
        text = _complete(client, system_prompt, user_prompt)
        parsed = _parse_numbered_response(text, len(chunk))
        for entry, line in zip(chunk, parsed):
            if not line:
                continue
            if not _placeholders_match(entry["msgid"], line):
                # Don't ship translations where the model silently dropped or
                # invented a placeholder — the UI would render broken text.
                # Leave msgstr empty; next CI run will retry.
                src_ph = _placeholders(entry["msgid"])
                out_ph = _placeholders(line)
                print(
                    f"  [rejected] placeholder mismatch for {entry['msgid']!r}:\n"
                    f"    source placeholders: {src_ph}\n"
                    f"    output placeholders: {out_ph}",
                    file=sys.stderr,
                )
                rejected += 1
                continue
            warnings = _glossary_warnings(entry["msgid"], line, glossary)
            if warnings:
                # Ship it but surface the mismatch — humans see this in the
                # PR log and tighten the glossary or re-translate by hand.
                print(
                    f"  [glossary] {entry['msgid']!r} → {line!r}: "
                    + ", ".join(warnings),
                    file=sys.stderr,
                )
                glossary_warned += 1
            entry["msgstr"] = line
            filled += 1
    return {
        "filled": filled,
        "rejected_placeholder_mismatch": rejected,
        "glossary_warnings": glossary_warned,
        "capped": capped,
    }


# ---------------------------------------------------------------------------
# YAML file walking
# ---------------------------------------------------------------------------

def translate_yaml_tree(source_dir: Path, target_dir: Path, language: str) -> None:
    """For each `data/science/*/theory.yaml`, if no counterpart exists under
    `target_dir/<pillar>/theory.yaml`, translate the text fields with Claude
    and write the result.
    """
    import yaml

    client = _client()
    source_dir = source_dir.resolve()
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    translatable_keys = {"name", "description", "simple_description", "advanced_description"}

    created = 0
    for src_path in source_dir.rglob("*.yaml"):
        # Skip files already under target_dir
        try:
            src_path.relative_to(target_dir)
            continue
        except ValueError:
            pass
        rel = src_path.relative_to(source_dir)
        dst_path = target_dir / rel
        if dst_path.exists():
            continue

        with open(src_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        to_translate = {k: v for k, v in (data or {}).items()
                        if k in translatable_keys and isinstance(v, str) and v.strip()}
        if not to_translate:
            continue

        numbered = "\n\n".join(f"[{k}]\n{v}" for k, v in to_translate.items())
        text = _complete(
            client,
            build_system_prompt(),
            (
                f"Translate the following Praxys science YAML fields to {language}. "
                f"Preserve markdown formatting (headings, tables, lists, code). Keep "
                f"technical terms in English where standard. Output each field as "
                f"`[key]\\n<translation>` separated by blank lines, matching the input order:\n\n{numbered}"
            ),
        )
        translated = _parse_yaml_response(text, list(to_translate.keys()))
        new_data = dict(data)
        new_data.update(translated)

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dst_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(new_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        created += 1
        print(f"Created {dst_path.relative_to(target_dir.parent)}", file=sys.stderr)

    print(f"Translated {created} YAML files.", file=sys.stderr)


def _parse_yaml_response(text: str, keys: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []

    def _flush():
        if current_key and current_key in keys:
            out[current_key] = "\n".join(buf).strip()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            _flush()
            current_key = stripped[1:-1].strip()
            buf = []
        else:
            buf.append(line)
    _flush()
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("po", help="Translate missing entries in a .po file")
    po.add_argument("--source", required=True, type=Path)
    po.add_argument("--target", required=True, type=Path)
    po.add_argument("--language", required=True, help='e.g. "Simplified Chinese"')
    po.add_argument(
        "--max-translations",
        type=int,
        default=int(os.environ.get("TRANSLATE_MAX", "100")),
        help=(
            "Cost cap: max entries to translate in one run. Default 100 (or "
            "$TRANSLATE_MAX). When the cap is hit the remaining entries stay "
            "empty — the next CI run picks them up."
        ),
    )

    yml = sub.add_parser("yaml", help="Translate science YAML files")
    yml.add_argument("--source-dir", required=True, type=Path)
    yml.add_argument("--target-dir", required=True, type=Path)
    yml.add_argument("--language", required=True)

    args = p.parse_args()

    if args.cmd == "po":
        source_entries, _source_tail = parse_po(args.source)
        if args.target.exists():
            target_entries, target_tail = parse_po(args.target)
        else:
            target_entries, target_tail = [], []
        target_by_msgid = {e["msgid"]: e for e in target_entries}
        # Obsolete blocks are catalog-local: en's mean nothing in zh (they
        # carry English msgstrs for strings removed from source), while zh's
        # hold already-translated Chinese for the same — preserve zh's,
        # discard en's.
        obsolete_tail = _extract_obsolete_blocks(target_entries, target_tail)
        merged: list[dict] = []
        for e in source_entries:
            msgid = e["msgid"]
            existing = target_by_msgid.get(msgid)
            merged.append({
                "prefix_lines": _strip_obsolete(e["prefix_lines"]),
                "msgid": msgid,
                "msgstr": existing["msgstr"] if existing else "",
            })
        summary = translate_batch(
            merged,
            args.language,
            max_translations=args.max_translations,
        )
        args.target.parent.mkdir(parents=True, exist_ok=True)
        write_po(args.target, merged, tail=obsolete_tail)
        print(
            f"Wrote {args.target} — filled={summary['filled']}, "
            f"rejected_placeholder_mismatch={summary['rejected_placeholder_mismatch']}, "
            f"glossary_warnings={summary['glossary_warnings']}, "
            f"capped={summary['capped']}"
        )
        return 0

    if args.cmd == "yaml":
        translate_yaml_tree(args.source_dir, args.target_dir, args.language)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
