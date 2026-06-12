#!/usr/bin/env python3
"""
Minimal CLI to prototype a translation-pair word game using FreeDict TEI XML.

Default source files:
  https://download.freedict.org/generated/eng-ita/eng-ita.tei
  https://download.freedict.org/generated/ita-eng/ita-eng.tei

Examples:
  python3 wordpair.py build
  python3 wordpair.py ask --en-start C --en-len 6 --it-start C --it-len 5
  python3 wordpair.py solve --en-start C --en-len 6 --it-start C --it-len 5 --limit 10
  python3 wordpair.py check coffee caffè
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from itertools import chain
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Iterator

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
ENTRY_TAG = f"{{{TEI_NS}}}entry"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "wordpair"
PAIR_DB_NAME = "pairs.json"
META_NAME = "metadata.json"
URLS = {
    "eng-ita": "https://download.freedict.org/generated/eng-ita/eng-ita.tei",
    "ita-eng": "https://download.freedict.org/generated/ita-eng/ita-eng.tei",
}


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def letters_only(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFC", text) if ch.isalpha())


def normalized_text(text: str, *, fold_accents: bool = False) -> str:
    text = unicodedata.normalize("NFC", text).strip().casefold()
    return strip_accents(text) if fold_accents else text


def word_shape(text: str) -> tuple[str, int] | None:
    letters = letters_only(text)
    if not letters:
        return None
    initial = strip_accents(letters[0]).upper()
    return initial, len(letters)


def is_single_word_candidate(text: str) -> bool:
    text = unicodedata.normalize("NFC", text).strip()
    if not text:
        return False
    banned = set(",;/|()[]{}:!?0123456789")
    if any(ch in banned for ch in text):
        return False
    if any(ch.isspace() for ch in text):
        return False
    if "-" in text:
        return False
    allowed_extra = set("'’`")
    if not all(ch.isalpha() or ch in allowed_extra for ch in text):
        return False
    return bool(letters_only(text))


def entry_pairs_from_tei(path: Path, src_lang: str) -> Iterator[tuple[str, str]]:
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != ENTRY_TAG:
            continue

        source_words = []
        for orth in elem.findall("./tei:form/tei:orth", NS):
            if orth.text:
                source_words.append(orth.text.strip())

        target_words = []
        for quote in elem.findall(".//tei:cit[@type='trans']/tei:quote", NS):
            if quote.text:
                target_words.append(quote.text.strip())

        for src in source_words:
            if not is_single_word_candidate(src):
                continue
            for tgt in target_words:
                if not is_single_word_candidate(tgt):
                    continue
                if src_lang == "eng":
                    yield (src, tgt)
                else:
                    yield (tgt, src)

        elem.clear()


def dedupe_pairs(pairs: Iterable[tuple[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for en, it in pairs:
        key = (normalized_text(en), normalized_text(it))
        if key in seen:
            continue
        seen.add(key)
        out.append({"en": unicodedata.normalize("NFC", en), "it": unicodedata.normalize("NFC", it)})
    return out


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, dest.open("wb") as fh:
        fh.write(response.read())


def load_pairs(cache_dir: Path) -> list[dict[str, str]]:
    pair_path = cache_dir / PAIR_DB_NAME
    if not pair_path.exists():
        raise SystemExit(
            f"Pair database not found at {pair_path}. Run: {Path(sys.argv[0]).name} build"
        )
    return json.loads(pair_path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_build(args: argparse.Namespace) -> int:
    cache_dir = args.cache_dir
    tei_dir = cache_dir / "tei"
    eng_tei = tei_dir / "eng-ita.tei"
    ita_tei = tei_dir / "ita-eng.tei"

    if args.redownload or not eng_tei.exists():
        print(f"Downloading {URLS['eng-ita']}", file=sys.stderr)
        download(URLS["eng-ita"], eng_tei)
    if args.redownload or not ita_tei.exists():
        print(f"Downloading {URLS['ita-eng']}", file=sys.stderr)
        download(URLS["ita-eng"], ita_tei)

    print("Parsing FreeDict TEI...", file=sys.stderr)
    pairs = dedupe_pairs(
        chain(entry_pairs_from_tei(eng_tei, "eng"), entry_pairs_from_tei(ita_tei, "ita"))
    )

    save_json(cache_dir / PAIR_DB_NAME, pairs)
    save_json(
        cache_dir / META_NAME,
        {
            "sources": URLS,
            "pair_count": len(pairs),
            "rule": "single-word pairs only; length counts alphabetic Unicode letters; spaces/hyphens excluded",
        },
    )
    print(f"Built {len(pairs)} unique English↔Italian pairs in {cache_dir / PAIR_DB_NAME}")
    return 0


def filter_pairs(
    pairs: Iterable[dict[str, str]],
    *,
    en_start: str | None,
    en_len: int | None,
    it_start: str | None,
    it_len: int | None,
) -> list[dict[str, str]]:
    out = []
    for pair in pairs:
        en_shape = word_shape(pair["en"])
        it_shape = word_shape(pair["it"])
        if not en_shape or not it_shape:
            continue
        if en_start and en_shape[0] != strip_accents(en_start[0]).upper():
            continue
        if en_len and en_shape[1] != en_len:
            continue
        if it_start and it_shape[0] != strip_accents(it_start[0]).upper():
            continue
        if it_len and it_shape[1] != it_len:
            continue
        out.append(pair)
    return out


def print_prompt(pair: dict[str, str]) -> None:
    en_initial, en_len = word_shape(pair["en"])  # type: ignore[misc]
    it_initial, it_len = word_shape(pair["it"])  # type: ignore[misc]
    print(
        f"Find a word that starts with {en_initial} and has {en_len} letters in English, "
        f"and starts with {it_initial} and has {it_len} letters in Italian."
    )


def cmd_ask(args: argparse.Namespace) -> int:
    pairs = load_pairs(args.cache_dir)
    matches = filter_pairs(
        pairs,
        en_start=args.en_start,
        en_len=args.en_len,
        it_start=args.it_start,
        it_len=args.it_len,
    )
    if not matches:
        print("No matching translation pair found.")
        return 1

    pair = random.choice(matches)
    print_prompt(pair)
    if args.reveal:
        print(f"One solution: {pair['en']} / {pair['it']}")
    else:
        print("Run with --reveal to show one solution, or use the check command.")
    return 0


def cmd_solve(args: argparse.Namespace) -> int:
    pairs = load_pairs(args.cache_dir)
    matches = filter_pairs(
        pairs,
        en_start=args.en_start,
        en_len=args.en_len,
        it_start=args.it_start,
        it_len=args.it_len,
    )
    random.shuffle(matches)
    matches = matches[: args.limit]
    if not matches:
        print("No matching translation pairs found.")
        return 1

    for pair in matches:
        en_shape = word_shape(pair["en"])
        it_shape = word_shape(pair["it"])
        print(
            f"{pair['en']} / {pair['it']} "
            f"(EN {en_shape[0]}{en_shape[1]}, IT {it_shape[0]}{it_shape[1]})"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    pairs = load_pairs(args.cache_dir)
    exact_keys = {(normalized_text(p['en']), normalized_text(p['it'])): p for p in pairs}
    loose_keys = {(normalized_text(p['en'], fold_accents=True), normalized_text(p['it'], fold_accents=True)): p for p in pairs}

    en = args.english
    it = args.italian
    exact_key = (normalized_text(en), normalized_text(it))
    loose_key = (normalized_text(en, fold_accents=True), normalized_text(it, fold_accents=True))

    if exact_key in exact_keys:
        pair = exact_keys[exact_key]
        print(f"Valid pair: {pair['en']} / {pair['it']}")
        return 0
    if loose_key in loose_keys:
        pair = loose_keys[loose_key]
        print(f"Found accent/case-folded match: {pair['en']} / {pair['it']}")
        return 0

    print("That pair was not found in the cached FreeDict-derived pair set.")
    print(f"English shape: {word_shape(en)}")
    print(f"Italian shape: {word_shape(it)}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prototype CLI word game using FreeDict English↔Italian pairs")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"Cache directory (default: {DEFAULT_CACHE_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Download FreeDict TEI files and build a local pair database")
    p_build.add_argument("--redownload", action="store_true", help="Force re-download of TEI files")
    p_build.set_defaults(func=cmd_build)

    def add_shape_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--en-start", help="English initial letter, e.g. C")
        p.add_argument("--en-len", type=int, help="English letter count, e.g. 6")
        p.add_argument("--it-start", help="Italian initial letter, e.g. C")
        p.add_argument("--it-len", type=int, help="Italian letter count, e.g. 5")

    p_ask = sub.add_parser("ask", help="Print one puzzle matching the requested shape")
    add_shape_args(p_ask)
    p_ask.add_argument("--reveal", action="store_true", help="Show one matching solution")
    p_ask.set_defaults(func=cmd_ask)

    p_solve = sub.add_parser("solve", help="List matching pairs for a requested shape")
    add_shape_args(p_solve)
    p_solve.add_argument("--limit", type=int, default=20, help="Maximum number of matches to print")
    p_solve.set_defaults(func=cmd_solve)

    p_check = sub.add_parser("check", help="Check whether an English/Italian pair exists in the cached data")
    p_check.add_argument("english", help="English candidate word")
    p_check.add_argument("italian", help="Italian candidate word")
    p_check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
