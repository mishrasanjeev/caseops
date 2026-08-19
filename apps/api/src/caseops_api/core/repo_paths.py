"""Locate the repository root without assuming it exists.

Counting directory levels - ``Path(__file__).resolve().parents[5]`` - is wrong
in a way that is invisible in the repo and fatal in the container. The API image
copies ``src`` and ``alembic`` into ``/app``, so a module at
``/app/src/caseops_api/services/x.py`` has exactly FIVE parents; ``parents[5]``
raises IndexError. In the checkout the same expression resolves fine, so the
defect never appears in a test run.

The IndexError fires at import time, which is what makes it worse than a wrong
path: it lands ABOVE any ``try``/``except`` a caller wrote to handle the file
being absent, so the guard that was supposed to report "unavailable" never runs.

Marker-based lookup instead. It returns None when there is no repository above
the caller - which is the truth in a deployed container - and lets each caller
decide what that means, rather than deciding for them by crashing.
"""

from __future__ import annotations

from pathlib import Path

# The API image ships neither of these, which is exactly why they identify a
# repository checkout rather than a deployment.
_MARKERS = (Path("docs") / "ip-implementation", Path(".git"))


def repo_root_or_none(start: Path | None = None) -> Path | None:
    """The repository root at or above ``start``, or None if there is none.

    ``start`` defaults to this file. Returning None is a supported answer, not
    an error: a deployed container legitimately has no repository above it.
    """

    origin = (start or Path(__file__)).resolve()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in _MARKERS):
            return candidate
    return None
