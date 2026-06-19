from __future__ import annotations

import re


def chunk_text(text: str, *, target_size: int = 900, max_size: int = 4000) -> list[str]:
    """Split text into chunks sized around ``target_size`` characters.

    ``max_size`` is a hard ceiling: oversized paragraphs are split at sentence
    boundaries, with a final hard slice when a sentence itself exceeds the cap.
    """
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if not paragraphs:
        paragraphs = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]

    sized: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_size:
            sized.append(paragraph)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        pending: list[str] = []
        pending_len = 0
        for sentence in sentences:
            if not sentence:
                continue
            if len(sentence) > max_size:
                if pending:
                    sized.append(" ".join(pending))
                    pending, pending_len = [], 0
                for i in range(0, len(sentence), max_size):
                    sized.append(sentence[i : i + max_size])
                continue
            if pending_len + len(sentence) + 1 > max_size and pending:
                sized.append(" ".join(pending))
                pending, pending_len = [sentence], len(sentence)
            else:
                pending.append(sentence)
                pending_len += len(sentence) + 1
        if pending:
            sized.append(" ".join(pending))

    chunks: list[str] = []
    buffer: list[str] = []
    current_size = 0
    for paragraph in sized:
        paragraph_size = len(paragraph)
        if buffer and current_size + paragraph_size + 1 > target_size:
            chunks.append("\n\n".join(buffer))
            buffer = [paragraph]
            current_size = paragraph_size
            continue
        buffer.append(paragraph)
        current_size += paragraph_size + 1
    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks
