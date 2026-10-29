# Bobine

Ton atelier TikTok perso, gratuit, qui tourne dans un GitHub Codespace. Deux usages :

- **Depuis un lien** : colle un article ou une idée, Bobine écrit le script avec Qwen et
  fabrique une vidéo neuve (voix off, images qui bougent, sous-titres mot à mot).
- **Depuis une vidéo** : envoie une de tes vidéos (cours, live, tuto), Bobine l'écoute,
  repère les meilleurs passages et les redécoupe en clips verticaux sous-titrés.

Dans les deux cas tu récupères la vidéo, sa légende et ses hashtags, prêtes à poster.

## Lancer Bobine dans Codespaces

1. Crée un dépôt GitHub (privé, c'est ton outil perso) et envoie-y tout le dossier `bobine`.
2. Sur la page du dépôt : **Code → Codespaces → Create codespace on main**.
3. Attends la fin de l'installation (10 à 15 minutes la première fois : ffmpeg, Python,
   le modèle de transcription et Qwen, environ 4 Go en tout).
4. Bobine s'ouvre toute seule dans un onglet. Sinon : onglet **PORTS**, ligne
   « Bobine (8000) », clic sur le globe.

Le port reste privé : seul toi, connecté à GitHub, peux ouvrir la page (y compris depuis
ton téléphone). Si Bobine ne répond plus, tape `./start.sh` dans le terminal.

## Redécouper une de tes vidéos

1. Onglet **Depuis une vidéo**, choisis le fichier (MP4, MOV, MKV ou WEBM).
   Pour une grosse vidéo, plus fiable : glisse-la dans le dossier `a-decouper` depuis
   l'explorateur du Codespace, puis choisis-la dans la liste « Ou reprends une vidéo ».
2. Choisis le nombre de clips et leur durée, puis **Trouver les meilleurs moments**.
   Bobine transcrit la vidéo (une seule fois : elle est gardée pour les fois suivantes),
   puis Qwen choisit les passages qui accrochent dès la première phrase.
3. Pour chaque clip proposé, tu peux le décocher, changer le titre, décaler le début ou
   la fin d'une seconde, changer le cadrage et retoucher la légende.
4. **Monter les clips**, puis **Télécharger** un par un ou **Tout télécharger (.zip)**.

**Cadrage** — « Auto » regarde chaque clip : si tu es filmé de près, l'image est recadrée
en vertical sur ton visage ; sinon (partage d'écran, tuto), tout l'écran reste visible au
milieu, sur un fond flou. Tu peux forcer « Visage », « Écran entier » ou « Centre ».

**Temps de calcul** sur la machine gratuite (2 cœurs) : la transcription prend à peu
près la durée de la vidéo avec le modèle `small`. Avec `WHISPER_MODEL=base`, c'est
environ trois fois plus rapide, un peu moins précis.

## Publier sur TikTok

Bobine ne publie pas à ta place : ouvre Bobine sur ton téléphone, télécharge le clip,
puis poste-le depuis l'appli TikTok en collant la légende (bouton « Copier la légende »).
C'est aussi le moment d'ajouter un son tendance à faible volume.

Pourquoi pas de publication automatique : l'API officielle de TikTok demande de créer
une appli développeur, et tant que TikTok ne l'a pas auditée (plusieurs semaines), tout
ce qu'elle publie reste en privé. Les robots qui se connectent à ton compte à ta place
sont interdits par TikTok et font risquer le blocage du compte.

## Créer une vidéo depuis un lien

1. Colle un lien d'article, de page produit, ou écris ton idée.
2. **Écrire le script** : chaque plan apparaît sur la bobine. Corrige le texte, change
   les mots-clés d'image, déplace, supprime ou ajoute un plan.
3. **Créer la vidéo**, puis **Télécharger la vidéo** et **Copier la légende**.

**Tout faire d'un coup** enchaîne les deux étapes sans t'arrêter sur le script.

## Réglages utiles (`.env`)

| Réglage | À quoi ça sert |
|---|---|
| `LLM_MODEL=qwen3.5:4b` | Le modèle Qwen local. `qwen3.5:2b` va plus vite, écrit un peu moins bien. |
| `LLM_PROVIDER=openai` + `LLM_BASE_URL` + `LLM_API_KEY` | Utiliser une API distante (OpenRouter, Groq…) : réponses en quelques secondes. |
| `WHISPER_MODEL=small` | Transcription : `base` plus rapide, `medium` plus précis. |
| `PEXELS_API_KEY` | Clé gratuite sur pexels.com/api : de vraies vidéos de fond pour le mode « lien ». |
| `X264_PRESET` | Vitesse du montage (`ultrafast`, `veryfast`, `medium`). |

Après un changement dans `.env`, relance `./start.sh`.

## Sous le capot

| Étape | Outil (gratuit) |
|---|---|
| Lecture d'un lien | requests + trafilatura |
| Script, choix des moments | Qwen via Ollama (ou API compatible OpenAI) ; sans IA, une sélection automatique plus simple |
| Transcription | faster-whisper, avec l'horodatage de chaque mot |
| Voix off (mode lien) | Edge TTS (voix neuronales Microsoft) ; secours : espeak-ng |
| Cadrage vertical | OpenCV (détection du visage) + ffmpeg |
| Sous-titres | Fichier ASS, 1 à 3 mots, le mot prononcé surligné, police Inter Display |
| Montage | ffmpeg, 1080 × 1920, 30 i/s, son normalisé pour TikTok |

Rangement : `sources/` garde tes vidéos envoyées et leur transcription, `output/` les
vidéos et clips finis (un dossier chacun, avec `meta.json` et la miniature).
Le Codespace gratuit offre 15 Go : supprime de temps en temps les vieilles sources.

## Bon à savoir

- Redécoupe uniquement des vidéos dont tu as les droits (les tiennes). Pour récupérer
  tes vidéos YouTube, passe par YouTube Studio → Contenu → Télécharger.
- Mode lien : les images d'un article de presse appartiennent au site. Pour tes propres
  pages c'est parfait ; sinon préfère Pexels ou les dégradés. La voix étant synthétique,
  active l'étiquette « contenu généré par IA » en publiant.
- Edge TTS est gratuit mais non officiel : s'il ne répond plus, Bobine passe sur la voix
  de secours (plus robotique) et le signale sous la vidéo.
- Musique de fond (mode lien) : dépose tes musiques libres de droits dans `music/`.

## Lancer en dehors de Codespaces (Linux)

```bash
sudo apt install ffmpeg espeak-ng
pip install -r requirements.txt
curl -fsSL https://ollama.com/install.sh | sh && ollama pull qwen3.5:4b
./start.sh
```

Puis ouvre http://localhost:8000.

Police Inter Display : licence SIL Open Font License (voir `fonts/licence/`).
