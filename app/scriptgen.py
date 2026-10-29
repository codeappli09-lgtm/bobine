"""Transforme le contenu d'un lien en script TikTok découpé en plans."""
from __future__ import annotations

import re
from collections import Counter

from . import llm
from .extract import Source

WORDS_PER_SECOND = 2.6  # débit d'une voix neuronale française à +8 %

TONES = {
    "choc": "rythmé et percutant, phrases très courtes, effet « wow », tension jusqu'à la fin",
    "histoire": "raconté comme une histoire, avec un personnage ou une situation, et une chute",
    "pedago": "pédagogique et clair, comme un prof qui explique simplement, avec un exemple concret",
    "humour": "drôle et complice, avec une pointe d'ironie, sans être lourd",
    "info": "factuel et neutre, comme un flash info rapide",
}

SYSTEM = """Tu es scénariste de vidéos TikTok françaises « faceless » (voix off + images + sous-titres).
Tu écris pour l'oral : phrases courtes, mots simples, tutoiement, aucune liste, aucun emoji,
aucun symbole, pas de markdown. Les nombres s'écrivent comme on les dit si c'est ambigu.
Tu n'inventes AUCUN fait : tout vient de la source fournie. Tu réponds uniquement en JSON."""

TEMPLATE = """SOURCE :
{source}

CONSIGNES :
- Durée visée : {duration} secondes, soit environ {words} mots au total (voix off).
- Ton : {tone}.
- Découpe en {n_min} à {n_max} plans. Chaque plan = 1 ou 2 phrases (8 à 30 mots).
- Plan 1 = l'accroche : 15 mots maximum, crée la curiosité ou la surprise dès la première seconde
  (question, chiffre fort, affirmation contre-intuitive). Ne commence pas par « Bonjour ».
- Les plans suivants livrent l'info la plus intéressante, un détail par plan, du plus fort au moins fort.
- Dernier plan = conclusion + appel à l'action : {cta}
- Pour chaque plan, « visuel » = 2 à 4 mots-clés EN ANGLAIS décrivant une vidéo de banque d'images
  qui illustre le plan (ex. « honey bee flower », « city traffic night »).
- « titre » = bandeau affiché en haut de la vidéo, 6 mots maximum, sans point final.
- « legende » = description TikTok de 150 caractères maximum, qui donne envie de regarder.
- « hashtags » = 4 à 6 hashtags pertinents, dont des larges et des précis.

Réponds avec ce JSON exactement :
{{"titre": "...", "segments": [{{"texte": "...", "visuel": "..."}}], "legende": "...", "hashtags": ["#...", "#..."]}}"""


def _plan_bounds(duration: int) -> tuple[int, int]:
    if duration <= 30:
        return 4, 6
    if duration <= 45:
        return 5, 8
    return 6, 10


def clean_spoken(text: str) -> str:
    """Retire ce qu'une voix off lirait mal (emojis, liens, markdown)."""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|~\[\]{}]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]", "", text)
    text = text.replace("…", "...").replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize(data: dict, fallback_title: str = "") -> dict:
    segments = []
    for seg in data.get("segments") or []:
        if isinstance(seg, str):
            seg = {"texte": seg}
        texte = clean_spoken(str(seg.get("texte") or seg.get("text") or ""))
        if not texte:
            continue
        visuel = str(seg.get("visuel") or seg.get("visual") or seg.get("keywords") or "")
        segments.append({"texte": texte, "visuel": clean_spoken(visuel)[:60]})
    if not segments:
        raise llm.LLMError("Le script ne contient aucun plan.")

    titre = clean_spoken(str(data.get("titre") or data.get("title") or fallback_title))
    titre = short_banner(titre, 8)

    hashtags = []
    raw = data.get("hashtags") or []
    if isinstance(raw, str):
        raw = raw.split()
    for tag in raw:
        tag = re.sub(r"[^\w#]", "", str(tag).strip())
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + tag
        if tag.lower() not in [h.lower() for h in hashtags]:
            hashtags.append(tag)

    legende = str(data.get("legende") or data.get("caption") or "").strip()
    return {
        "titre": titre,
        "segments": segments,
        "legende": legende[:300],
        "hashtags": hashtags[:8],
    }


def estimate_seconds(script: dict) -> float:
    words = sum(len(s["texte"].split()) for s in script["segments"])
    return round(words / WORDS_PER_SECOND + 0.15 * len(script["segments"]), 1)


def write_script(source: Source, duration: int = 45, tone: str = "choc",
                 cta: str = "", use_ai: bool = True) -> dict:
    duration = max(15, min(int(duration), 90))
    n_min, n_max = _plan_bounds(duration)
    cta_text = cta.strip() or "invite à s'abonner pour la suite, en une phrase naturelle"
    if cta.strip():
        cta_text = f"termine par cette idée, reformulée naturellement : « {cta.strip()} »"

    if use_ai:
        prompt = TEMPLATE.format(
            source=source.as_prompt(),
            duration=duration,
            words=int(duration * WORDS_PER_SECOND),
            tone=TONES.get(tone, TONES["choc"]),
            n_min=n_min,
            n_max=n_max,
            cta=cta_text,
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                raw = llm.chat(SYSTEM, prompt, temperature=0.8 if attempt == 0 else 0.5)
                script = normalize(llm.parse_json(raw), fallback_title=source.title)
                script["mode"] = "ia"
                break
            except llm.LLMError as exc:
                last_error = exc
        else:
            raise llm.LLMError(str(last_error))
    else:
        script = simple_script(source, duration, cta)
        script["mode"] = "simple"

    script["duree_estimee"] = estimate_seconds(script)
    script["source"] = {"type": source.kind, "url": source.url, "titre": source.title,
                        "site": source.site, "images": source.images}
    return script


# --- Mode sans IA ------------------------------------------------------------
STOPWORDS = set("""le la les un une des du de d l et ou à au aux en dans sur pour par avec sans
ce cet cette ces son sa ses leur leurs qui que quoi dont où il elle ils elles on nous vous je tu
est sont été être a ont avoir fait faire plus moins très tout tous toute toutes aussi mais donc
car ne pas se s y comme entre après avant depuis selon lors cela ça c qu n m t j
jusqu afin lorsque puis""".split())


def _sentences(text: str, skip: str = "", min_words: int = 6) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = clean_spoken(line)
        if not line or not re.search(r"[.!?…]$", line) and len(line.split()) < 12:
            continue  # intertitre ou bout de menu
        for part in re.split(r"(?<=[.!?])\s+", line):
            if min_words <= len(part.split()) <= 40 and part.lower() != skip.lower():
                if part not in out:
                    out.append(part)
    return out


def short_banner(title: str, max_words: int) -> str:
    """Coupe un titre trop long sans le finir sur « de », « en », « la »…"""
    words = title.rstrip(".").split()
    if len(words) <= max_words:
        return " ".join(words)
    words = words[:max_words]
    while len(words) > 2 and words[-1].lower().strip("'") in STOPWORDS:
        words.pop()
    return " ".join(words)


def simple_script(source: Source, duration: int, cta: str = "") -> dict:
    """Script de secours quand l'IA n'est pas disponible : extraits de la source."""
    budget = int(duration * WORDS_PER_SECOND)
    is_idea = source.kind == "idee"
    pool = _sentences(source.description + "\n" + source.text, skip=source.title,
                      min_words=3 if is_idea else 6)
    if not pool and source.text:
        pool = [clean_spoken(source.text)[:200]]
    title = clean_spoken(source.title) or (pool[0] if pool else "Le saviez-tu")

    words_all = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]{4,}", (source.title + " " + source.text).lower())
    common = [w for w, _ in Counter(w for w in words_all if w not in STOPWORDS).most_common(3)]
    visual = " ".join(common[:2]) or "abstract"

    if is_idea and pool:
        hook = pool.pop(0)  # l'idée commence déjà par sa meilleure phrase
    elif len(title.split()) <= 12:
        hook = f"Écoute bien ça : {title.rstrip('.')}."
    else:
        hook = "Arrête-toi deux secondes, ça vaut le coup."
    segments = [{"texte": hook, "visuel": visual}]
    used = len(hook.split())
    for sentence in pool:
        n = len(sentence.split())
        if used + n > budget - 12:
            break
        segments.append({"texte": sentence, "visuel": visual})
        used += n
    end = clean_spoken(cta) or "Abonne-toi pour ne rien rater de la suite."
    if not re.search(r"[.!?…]$", end):
        end += "."
    segments.append({"texte": end, "visuel": visual})

    tags = ["#apprendresurtiktok", "#lesaviezvous"] + [f"#{w}" for w in common[:3]]
    short_title = short_banner(title, 6)
    return {
        "titre": short_title,
        "segments": segments,
        "legende": (source.description or title)[:150],
        "hashtags": tags,
    }
