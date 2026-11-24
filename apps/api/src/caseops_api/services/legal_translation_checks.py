"""Deterministic integrity checks for legal-document OCR and translation.

Machine translation of a court record must not drop, add or alter case
numbers, CNR numbers, dates, amounts, section/article numbers, citations or
paragraph numbering. These checks compare what can be compared without a
model: every digit sequence (Devanagari digits normalised), every mixed
letter-digit identifier, and a fixed set of law-report and statute
abbreviations. A mismatch never "fixes" the text; it flags the paragraph for
human review.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# Devanagari (U+0966-096F) and other Indic digit forms -> ASCII.
_DIGIT_MAP = str.maketrans({chr(0x0966 + i): str(i) for i in range(10)})
# Digits glued after letters belong to an identifier (checked separately).
_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:,\d{2,3})*")
_IDENTIFIER = re.compile(r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{5,}\b")
# Abbreviations that must survive translation verbatim (law reports, codes).
PROTECTED_ABBREVIATIONS = frozenset({
    "AIR", "SCC", "SCR", "SCALE", "JT", "DLT", "INSC", "MANU", "ILR", "CrLJ", "SCC OnLine",
    "IPC", "CrPC", "CPC", "BNS", "BNSS", "BSA", "NDPS", "POCSO", "PMLA", "NI", "GST",
    "FIR", "CNR", "SLP", "PIL",
})
_ABBREVIATION = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(sorted((re.escape(item) for item in PROTECTED_ABBREVIATIONS), key=len, reverse=True))
    + r")(?![A-Za-z])"
)
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")
UNCLEAR_MARKERS = ("�",)
MIN_OMISSION_SOURCE_CHARS = 80
MIN_LENGTH_RATIO = 0.35


@dataclass(frozen=True, slots=True)
class Segment:
    """One request item: a paragraph, or a sentence-aligned piece of one."""

    paragraph_index: int
    text: str


def normalise_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


def number_tokens(text: str) -> Counter[str]:
    tokens: Counter[str] = Counter()
    for match in _NUMBER.finditer(normalise_digits(text)):
        value = match.group(0).replace(",", "").lstrip("0") or "0"
        tokens[value] += 1
    return tokens


def identifier_tokens(text: str) -> Counter[str]:
    return Counter(match.group(0).upper() for match in _IDENTIFIER.finditer(normalise_digits(text)))


def abbreviation_tokens(text: str) -> Counter[str]:
    return Counter(match.group(1) for match in _ABBREVIATION.finditer(text))


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in _PARAGRAPH_BREAK.split(text or "") if part.strip()]


def _split_long(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > limit:
            # A single run-on sentence: break on whitespace, never mid-word.
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return [piece for piece in pieces if piece]


def segment_paragraphs(paragraphs: list[str], *, limit: int) -> list[Segment]:
    segments: list[Segment] = []
    for index, paragraph in enumerate(paragraphs):
        if len(paragraph) <= limit:
            segments.append(Segment(index, paragraph))
        else:
            segments.extend(Segment(index, piece) for piece in _split_long(paragraph, limit))
    return segments


def batch_segments(
    segments: list[Segment], *, max_chars: int, max_items: int,
) -> list[list[Segment]]:
    batches: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0
    for segment in segments:
        if current and (size + len(segment.text) > max_chars or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        current.append(segment)
        size += len(segment.text)
    if current:
        batches.append(current)
    return batches


def check_translation(source: str, translated: str) -> list[str]:
    """Return review flags for one paragraph; an empty list means no finding."""

    flags: list[str] = []
    if source.strip() and not translated.strip():
        return ["empty_translation"]
    source_numbers = number_tokens(source)
    translated_numbers = number_tokens(translated)
    if source_numbers - translated_numbers:
        flags.append("number_missing")
    if translated_numbers - source_numbers:
        flags.append("number_added")
    if identifier_tokens(source) - identifier_tokens(translated):
        flags.append("identifier_changed")
    if abbreviation_tokens(source) - abbreviation_tokens(translated):
        flags.append("citation_abbreviation_changed")
    if (
        len(source.strip()) >= MIN_OMISSION_SOURCE_CHARS
        and len(translated.strip()) < MIN_LENGTH_RATIO * len(source.strip())
    ):
        flags.append("possible_omission")
    if any(marker in source for marker in UNCLEAR_MARKERS):
        flags.append("unclear_source")
    return flags


def missing_details(source: str, translated: str) -> dict[str, list[str]]:
    """Which numbers/identifiers differ, for the reviewer's side panel."""

    return {
        "missing_numbers": sorted((number_tokens(source) - number_tokens(translated)).elements()),
        "added_numbers": sorted((number_tokens(translated) - number_tokens(source)).elements()),
        "missing_identifiers": sorted(
            (identifier_tokens(source) - identifier_tokens(translated)).elements()
        ),
        "missing_abbreviations": sorted(
            (abbreviation_tokens(source) - abbreviation_tokens(translated)).elements()
        ),
    }


__all__ = [
    "PROTECTED_ABBREVIATIONS",
    "Segment",
    "batch_segments",
    "check_translation",
    "identifier_tokens",
    "missing_details",
    "normalise_digits",
    "number_tokens",
    "segment_paragraphs",
    "split_paragraphs",
]
