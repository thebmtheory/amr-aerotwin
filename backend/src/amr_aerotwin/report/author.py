"""Report author details, kept in one place.

The build fills them into the page's masthead byline, metadata and footer, and into the technical note's byline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Author:
    name: str
    email: str
    line: str  # one sentence under the name


AUTHOR = Author(
    name="Balaji Murugan",
    email="thebm.theory@gmail.com",
    line="Built as an independent project for the Graduate Data Scientist (Vehicle Science) application.",
)
