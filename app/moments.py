"""Repère dans une transcription les passages qui feront de bons clips TikTok."""
from __future__ import annotations

import math
import re
from typing import Callable

from . import llm
from .scriptgen import short_banner

LENGTHS = {"court": (20, 40), "moyen": (30, 60), "long": (45, 90)}
CONNECTORS = ("et ", "donc", "du coup", "mais ", "alors", "voilà", "euh", "bon ", "enfin",
              "ensuite", "puis ", "après ", "parce que", "c'est-à-dire")
HOOK_WORDS = ("pourquoi", "comment", "secret", "erreur", "astuce", "savais", "jamais",
              "personne", "arrête", "attention", "voici", "le problème", "la vérité", "gratuit",
              "en 2 minutes", "en deux minutes", "le meilleur", "le pire", "incroyable")


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def phrases(transcript: dict) -> list[dict]:
    """Recoupe la transcription en phrases (unité de base d'un clip)."""
    out: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                        "text": " ".join(w["text"] for w in cur), "words": list(cur)})
            cur.clear()

    for seg in transcript["segments"]:
        words = seg.get("words") or [{"text": seg["text"], "start": seg["start"],
                                      "end": seg["end"]}]
        for w in words:
            if cur and (w["start"] - cur[-1]["end"] > 0.8 or len(cur) >= 30):
                flush()
            cur.append(w)
            if re.search(r"[.!?…]$", w["text"]):
                flush()
        if cur and len(cur) > 18:
            flush()
    flush()
    for i, p in enumerate(out):
        p["i"] = i
    return out


def _fit(ph: list[dict], a: int, b: int, lo: float, hi: float) -> tuple[int, int]:
    """Allonge ou raccourcit un passage pour tenir dans [lo, hi] secondes."""
    a, b = max(0, a), min(len(ph) - 1, b)
    if b < a:
        b = a
    dur = lambda x, y: ph[y]["end"] - ph[x]["start"]
    while dur(a, b) > hi and b > a:
        b -= 1
    while dur(a, b) < lo:
        if b + 1 < len(ph) and dur(a, b + 1) <= hi:
            b += 1
        elif a > 0 and dur(a - 1, b) <= hi:
            a -= 1
        else:
            break
    return a, b


def _clip(ph: list[dict], a: int, b: int, total: float, extra: dict) -> dict:
    start = max(0.0, ph[a]["start"] - 0.2)
    end = min(total, ph[b]["end"] + 0.35)
    text = " ".join(p["text"] for p in ph[a:b + 1])
    clip = {"start": round(start, 2), "end": round(end, 2), "debut": a, "fin": b,
            "texte": text[:600], "titre": "", "legende": "", "hashtags": [], "score": 5,
            "raison": ""}
    clip.update({k: v for k, v in extra.items() if v not in (None, "")})
    if not clip["titre"]:
        clip["titre"] = short_banner(ph[a]["text"], 8)
    return clip


def _overlap(x: dict, y: dict) -> float:
    inter = min(x["end"], y["end"]) - max(x["start"], y["start"])
    return max(0.0, inter) / max(min(x["end"] - x["start"], y["end"] - y["start"]), 0.1)


def _pick(cands: list[dict], count: int) -> list[dict]:
    chosen: list[dict] = []
    for c in sorted(cands, key=lambda c: (-c["score"], c["end"] - c["start"])):
        if all(_overlap(c, o) < 0.1 for o in chosen):
            chosen.append(c)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda c: c["start"])


# --- Avec l'IA -------------------------------------------------------------------
SYSTEM = """Tu es monteur vidéo spécialiste de TikTok. On te donne la transcription numérotée
d'une longue vidéo en français. Tu repères les passages qui, découpés seuls, feront de bons
clips TikTok. Tu réponds uniquement en JSON."""

TEMPLATE = """TRANSCRIPTION (numéro, minute:seconde, durée de la ligne, texte) :
{lines}

CONSIGNES :
- Propose jusqu'à {k} passages. Chaque passage = une suite continue de lignes, de « debut » à
  « fin » (numéros inclus), qui dure entre {lo} et {hi} secondes au total.
- Le passage doit se comprendre sans le reste de la vidéo : une idée complète, une fin nette.
- La première ligne doit accrocher : question, affirmation surprenante, promesse, chiffre fort.
  Ne commence jamais par « et », « donc », « du coup », « voilà », « alors ».
- « score » : de 1 à 10, potentiel de vues sur TikTok (sois exigeant).
- « titre » : bandeau affiché en haut du clip, 6 mots maximum, sans point final.
- « legende » : description TikTok de 150 caractères maximum.
- « hashtags » : 3 à 5 hashtags pertinents.
- « raison » : en une phrase, pourquoi ce passage marche.

Réponds avec ce JSON :
{{"clips": [{{"debut": 0, "fin": 0, "score": 0, "titre": "...", "legende": "...", "hashtags": ["#..."], "raison": "..."}}]}}"""


def _ai_window(ph: list[dict], lo: int, hi: int, total: float, k: int,
               length: tuple[int, int]) -> list[dict]:
    lines = "\n".join(
        f"[{p['i']}] {mmss(p['start'])} ({p['end'] - p['start']:.0f} s) {p['text']}"
        for p in ph[lo:hi])
    prompt = TEMPLATE.format(lines=lines, k=k, lo=length[0], hi=length[1])
    data = llm.parse_json(llm.chat(SYSTEM, prompt, temperature=0.4))
    raw = data.get("clips") if isinstance(data, dict) else data
    out = []
    for c in raw or []:
        try:
            a, b = int(c.get("debut")), int(c.get("fin"))
        except (TypeError, ValueError):
            continue
        a, b = max(lo, min(a, hi - 1)), max(lo, min(b, hi - 1))
        a, b = _fit(ph, min(a, b), max(a, b), *length)
        tags = c.get("hashtags") or []
        if isinstance(tags, str):
            tags = tags.split()
        tags = ["#" + re.sub(r"[^\w]", "", str(t)) for t in tags if re.sub(r"[^\w]", "", str(t))]
        try:
            score = float(c.get("score") or 5)
        except (TypeError, ValueError):
            score = 5.0
        out.append(_clip(ph, a, b, total, {
            "titre": short_banner(str(c.get("titre") or "").strip(), 8),
            "legende": str(c.get("legende") or "")[:300],
            "hashtags": tags[:6], "score": max(1.0, min(score, 10.0)),
            "raison": str(c.get("raison") or "")[:200]}))
    return out


def find_with_ai(ph: list[dict], total: float, count: int, length: tuple[int, int],
                 progress: Callable[[float, str], None]) -> list[dict]:
    words_total = sum(len(p["text"].split()) for p in ph) or 1
    windows, start, acc = [], 0, 0
    for i, p in enumerate(ph):
        acc += len(p["text"].split())
        if acc >= 1100:
            windows.append((start, i + 1))
            start, acc = i + 1, 0
    if start < len(ph):
        windows.append((start, len(ph)))
    cands: list[dict] = []
    for n, (lo, hi) in enumerate(windows):
        progress(n / len(windows), f"Qwen lit la partie {n + 1}/{len(windows)}")
        share = sum(len(p["text"].split()) for p in ph[lo:hi]) / words_total
        k = max(2, math.ceil(count * share) + 1)
        try:
            cands += _ai_window(ph, lo, hi, total, k, length)
        except llm.LLMError:
            continue
    return _pick(cands, count)


# --- Sans IA -----------------------------------------------------------------------
def find_simple(ph: list[dict], total: float, count: int,
                length: tuple[int, int]) -> list[dict]:
    """Sans IA : on note chaque passage possible (questions, chiffres, mots forts,
    bonne première phrase) et on garde les meilleurs sans chevauchement."""
    lo, hi = length
    cands = []
    for a in range(len(ph)):
        first = ph[a]["text"].lower()
        hook = 3 if first.rstrip().endswith("?") or any(first.startswith(h) for h in HOOK_WORDS) else 0
        hook -= 4 if first.startswith(CONNECTORS) else 0
        for b in range(a, len(ph)):
            dur = ph[b]["end"] - ph[a]["start"]
            if dur > hi:
                break
            if dur < lo * 0.9:
                continue
            text = " ".join(p["text"] for p in ph[a:b + 1]).lower()
            n_words = max(len(text.split()), 1)
            score = (2 * text.count("?") + text.count("!") + len(re.findall(r"\d", text)) * 0.5
                     + sum(text.count(h) for h in HOOK_WORDS) * 1.5) / math.sqrt(n_words) * 4
            score += hook
            score -= 0 if re.search(r"[.!?…]$", ph[b]["text"]) else 1.5
            score -= (dur - lo) / max(hi - lo, 1)  # à intérêt égal, le plus court gagne
            cands.append(_clip(ph, a, b, total, {
                "score": round(max(1.0, min(score + 4, 10.0)), 1),
                "raison": "Repéré sans IA (questions, chiffres, mots forts)"}))
    picked = _pick(cands, count)
    for c in picked:
        c["legende"] = c["texte"][:140].rsplit(" ", 1)[0] + "…"
        c["hashtags"] = ["#apprendresurtiktok", "#conseil"]
    return picked


def find_moments(transcript: dict, count: int, length_key: str, use_ai: bool,
                 progress: Callable[[float, str], None]) -> tuple[list[dict], list[dict], str]:
    ph = phrases(transcript)
    total = transcript["duration"]
    length = LENGTHS.get(length_key, LENGTHS["moyen"])
    if total < length[0] + 2:
        length = (max(5, int(total * 0.5)), max(8, int(total) - 1))
    count = max(1, min(int(count), 15))
    note = ""
    clips: list[dict] = []
    if use_ai:
        clips = find_with_ai(ph, total, count, length, progress)
        if not clips:
            note = "L'IA n'a rien renvoyé d'exploitable : passages repérés sans IA."
    if not clips:
        clips = find_simple(ph, total, count, length)
    return clips, ph, note
