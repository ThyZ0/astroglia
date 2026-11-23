"""Tokenization shared by search, routing and similarity."""
from __future__ import annotations

import re
import unicodedata

STOP = set("""
a an and are as at be been but by can could do does for from has have how i if in into is it its
me my no not of on or our should so that the their them then there these this those to use used
uses using via was we were what when where which while who why will with without you your yes
any all also more most other only own same such than too very just like before after about first
le la les un une des du de et ou en au aux ce ces cette mon ma mes ton ta tes son sa ses pour par
sur dans avec sans qui que quoi dont est sont etre avoir fait faire pas plus moins tres comme mais
donc car ni je tu il elle nous vous ils elles on se sa leur leurs y
""".split())

# shortcut: tiny FR->EN dev glossary so French tasks match English skill descriptions;
# replace with multilingual embeddings once the routing bench shows cross-language misses.
FR_EN = {
    "analyse": "analyze", "analyser": "analyze", "corriger": "fix", "correction": "fix", "bogue": "bug",
    "erreur": "error", "erreurs": "error", "tester": "test", "tests": "test", "revue": "review",
    "relire": "review", "synchronisation": "sync", "donnees": "data", "fichier": "file", "fichiers": "file",
    "projet": "project", "navigateur": "browser", "recherche": "search", "chercher": "search",
    "memoire": "memory", "graphe": "graph", "connaissances": "knowledge", "deployer": "deploy",
    "securite": "security", "planifier": "plan", "plan": "plan", "tableur": "spreadsheet",
    "diapositives": "slides", "presentation": "presentation", "document": "document", "ameliorer": "improve",
    "simplifier": "simplify", "nettoyer": "clean", "outil": "tool", "outils": "tool", "competence": "skill",
    "competences": "skill", "pdf": "pdf", "courriel": "email", "calendrier": "calendar", "cartes": "flashcards",
    "examen": "exam", "reviser": "study", "cours": "course", "construire": "build", "creer": "create",
    "ecrire": "write", "lire": "read", "modifier": "edit", "supprimer": "delete", "base": "database",
}


def fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def terms(s: str) -> list[str]:
    """Lowercased, accent-folded, stopword-free word list, FR terms mapped to EN equivalents added."""
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9_+#.-]*[a-z0-9+#]|[a-z0-9]", fold(s)):
        if len(w) < 2 or w in STOP:
            continue
        out.append(w)
        if w in FR_EN and FR_EN[w] != w:
            out.append(FR_EN[w])
    return out


def fts_query(s: str) -> str:
    """Build a safe FTS5 OR-query (every term quoted, prefix match for longer words)."""
    uniq = list(dict.fromkeys(t.replace('"', "") for t in terms(s)))
    return " OR ".join(f'"{t}"*' if len(t) >= 4 else f'"{t}"' for t in uniq)


def est_tokens(s: str) -> int:
    """Rough token estimate (~4 chars/token). Always labelled an estimate in outputs."""
    return max(1, len(s) // 4)
