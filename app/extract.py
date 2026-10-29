"""Récupère le contenu d'un lien (titre, texte, images) ou d'une idée tapée."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import USER_AGENT

try:
    import trafilatura
except ImportError:  # trafilatura est optionnel
    trafilatura = None


@dataclass
class Source:
    kind: str  # "lien" ou "idee"
    url: str = ""
    title: str = ""
    description: str = ""
    text: str = ""
    site: str = ""
    images: list[str] = field(default_factory=list)

    def as_prompt(self, max_chars: int = 6000) -> str:
        parts = []
        if self.title:
            parts.append(f"TITRE : {self.title}")
        if self.site:
            parts.append(f"SITE : {self.site}")
        if self.description:
            parts.append(f"RÉSUMÉ : {self.description}")
        if self.text:
            parts.append("TEXTE :\n" + self.text[:max_chars])
        return "\n".join(parts)


URL_RE = re.compile(r"^https?://\S+$", re.I)


def is_url(value: str) -> bool:
    return bool(URL_RE.match(value.strip()))


def from_input(value: str) -> Source:
    value = value.strip()
    if not value:
        raise ValueError("Colle un lien ou écris une idée de vidéo.")
    if is_url(value):
        return fetch_url(value)
    return Source(kind="idee", title="", text=value)


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_url(url: str) -> Source:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"},
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(
            f"Impossible d'ouvrir ce lien ({exc.__class__.__name__}). "
            "Vérifie l'adresse, ou colle directement le texte de l'article."
        ) from exc

    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding
    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    title = _meta(soup, "og:title", "twitter:title") or (
        soup.title.get_text(strip=True) if soup.title else ""
    )
    description = _meta(soup, "og:description", "description", "twitter:description")
    site = _meta(soup, "og:site_name") or urlparse(resp.url).netloc.replace("www.", "")

    text = ""
    if trafilatura is not None:
        try:
            text = trafilatura.extract(html, include_comments=False, favor_recall=True) or ""
        except Exception:
            text = ""
    if len(text) < 200:
        for bad in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            bad.decompose()
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all(["p", "li", "h2", "h3"])]
        text = "\n".join(p for p in paragraphs if len(p) > 40)

    images: list[str] = []
    for key in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        val = _meta(soup, key)
        if val:
            images.append(urljoin(resp.url, val))
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src or src.startswith("data:"):
            continue
        low = src.lower()
        if any(x in low for x in (".svg", ".gif", "logo", "icon", "avatar", "pixel", "sprite")):
            continue
        images.append(urljoin(resp.url, src))
    seen, unique = set(), []
    for im in images:
        if im not in seen:
            seen.add(im)
            unique.append(im)

    source = Source(
        kind="lien",
        url=resp.url,
        title=_clean(title),
        description=_clean(description),
        text=_clean(text),
        site=site,
        images=unique[:10],
    )
    if not (source.title or source.text or source.description):
        raise ValueError(
            "Ce lien ne contient pas de texte lisible. Colle plutôt le texte ou décris l'idée."
        )
    return source
