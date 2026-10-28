"""Report author details, kept in one place.

The build fills them into the page's masthead byline, metadata and footer, and into the technical note's byline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Author:
    name: str
    degree: str
    email: str
    phone: str  # as shown; the tel: link drops the spaces
    linkedin: str  # profile URL
    line: str  # one sentence under the name
    repo: str  # where the code lives, linked from the footer

    @property
    def tel(self) -> str:
        return "".join(c for c in self.phone if c.isdigit() or c == "+")

    @property
    def linkedin_label(self) -> str:
        return self.linkedin.rstrip("/").rsplit("/", 1)[-1]  # profile name

    @property
    def repo_label(self) -> str:
        return "/".join(self.repo.rstrip("/").split("/")[-2:])  # owner/name


AUTHOR = Author(
    name="Balaji Murugan",
    degree="MSc Artificial Intelligence, University of Surrey",
    email="thebm.theory@gmail.com",
    phone="+44 7810 817440",
    linkedin="https://www.linkedin.com/in/balajimurugan-ai",
    line="Built as an independent project for the Graduate Data Scientist (Vehicle Science) application.",
    repo="https://github.com/thebmtheory/amr-aerotwin",
)
