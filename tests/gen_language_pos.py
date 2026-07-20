"""Regenerate localized strings.po files from language_translations.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
ENGLISH = ROOT / "resources" / "language" / "English" / "strings.po"
OUT_ROOT = ROOT / "resources" / "language"
TRANSLATIONS = TESTS / "language_translations.json"

LOCALES = {
    "resource.language.fr_fr": "fr",
    "resource.language.nl_nl": "nl",
    "resource.language.de_de": "de",
    "resource.language.es_es": "es",
    "resource.language.it_it": "it",
    "resource.language.el_gr": "el",
    "resource.language.nb_no": "nb",
    "resource.language.da_dk": "da",
    "resource.language.sv_se": "sv",
}


def parse_english(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    entries: list[tuple[str, str]] = []
    for match in re.finditer(
        r'msgctxt "(#[0-9]+)"\s*\nmsgid "(.*?)"\s*\nmsgstr "(.*?)"',
        text,
        re.DOTALL,
    ):
        msgid = match.group(2).replace("\\n", "\n").replace('\\"', '"')
        entries.append((match.group(1), msgid))
    return entries


def escape_po(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def placeholder_signature(text: str) -> list[str]:
    return re.findall(r"%[sd]|%\([^)]+\)[sd]", text)


def write_po(
    locale_dir: str,
    lang_code: str,
    entries: list[tuple[str, str]],
    translations: dict[str, str],
) -> int:
    out_dir = OUT_ROOT / locale_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Kodi language file",
        "# Addon: service.trickplay",
        'msgid ""',
        'msgstr ""',
        f'"Language: {lang_code}\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        "",
    ]
    missing = 0
    placeholder_mismatches = 0
    for msgctxt, msgid in entries:
        translated = translations.get(msgid)
        if translated is None:
            missing += 1
            translated = msgid
        if placeholder_signature(msgid) != placeholder_signature(translated):
            placeholder_mismatches += 1
            print(
                f"PLACEHOLDER MISMATCH [{lang_code}] {msgctxt}: "
                f"{msgid!r} -> {translated!r}"
            )
        lines.append(f'msgctxt "{msgctxt}"')
        lines.append(f'msgid "{escape_po(msgid)}"')
        lines.append(f'msgstr "{escape_po(translated)}"')
        lines.append("")
    (out_dir / "strings.po").write_text("\n".join(lines), encoding="utf-8")
    print(
        f"{locale_dir}: wrote {len(entries)} "
        f"(missing={missing}, placeholder_mismatches={placeholder_mismatches})"
    )
    return missing + placeholder_mismatches


def main() -> int:
    if not TRANSLATIONS.is_file():
        raise SystemExit(f"Missing {TRANSLATIONS}")
    entries = parse_english(ENGLISH)
    print(f"Parsed {len(entries)} English entries")
    merged = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    problems = 0
    for locale_dir, lang_code in LOCALES.items():
        if lang_code not in merged:
            raise SystemExit(f"No translations for {lang_code}")
        problems += write_po(locale_dir, lang_code, entries, merged[lang_code])
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
