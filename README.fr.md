<p align="center"><img src="docs/images/logo.svg" width="72" alt=""></p>

<h1 align="center">Astroglia</h1>

<p align="center"><b>Claude Code dispose déjà de dizaines de skills, plugins et serveurs MCP, et redécouvre vos projets à chaque session.<br>
Astroglia lui dit quelles ressources conviennent à la tâche, ce qu'il a déjà appris, et si c'est encore vrai.</b></p>

<p align="center">Local · aucun appel à un LLM · aucun cloud · Apache-2.0 · <a href="README.md">English</a></p>

![La galaxie Astroglia : capacités dans l'hémisphère gauche, mémoire et projets dans le droit](docs/images/galaxy.png)

*Les captures utilisent le jeu de données de démonstration fourni (`python bench/demo_seed.py <dossier>`), pas un usage réel.*

## Pourquoi

| À chaque session, Claude… | Avec Astroglia |
|---|---|
| relit `package.json`, le README et l'arborescence pour se rappeler ce qu'est un projet | reçoit une **fiche projet** dans le manifeste de démarrage (stack, commandes, points d'entrée, tests, fichiers les plus modifiés), construite depuis ces fichiers et reconstruite seulement quand ils changent |
| voit plus de 40 descriptions de skills et choisit au jugé ; des skills redondants sont chargés deux fois | appelle **`route(tâche)`** : une courte liste classée, avec la raison de chaque choix et de chaque rejet, sans doublons |
| oublie la correction trouvée hier, ou pire, se fie à une note sur du code qui a changé depuis | **`remember`** lie chaque note à l'empreinte de ses fichiers ; quand ils changent, la note est servie marquée **périmée** |
| ouvre `cache.py` sans savoir qu'une décision passée explique pourquoi le TTL vaut 600 | **mémoire ancrée** : ce qu'Astroglia sait d'un fichier arrive *quand Claude lit ce fichier*, sans aucune requête, marqué périmé si le fichier a changé ; le modifier liste les décisions qui risquent de ne plus tenir |
| termine une longue session et la connaissance est perdue | un **hook de fin de session** demande une seule fois, seulement après un vrai travail, s'il y a quelque chose à garder |

Les astrocytes sont les cellules du cerveau en forme d'étoile qui soutiennent les neurones sans penser à leur place. Astroglia ne pense pas pour Claude : il organise ce que Claude possède déjà.

## Installation

Python ≥ 3.11 et Claude Code. Installez d'abord la commande `astroglia` :

```bash
pipx install git+https://github.com/ThyZ0/astroglia
```

Puis choisissez **une seule** façon de la brancher (pas les deux, sinon les hooks s'exécutent deux fois) :

```text
# A. Comme plugin Claude Code (recommandé) : dans Claude Code
/plugin install astroglia --marketplace ThyZ0/astroglia
```

```bash
# B. Sans le système de plugins : modifie ~/.claude/settings.json (sauvegardé) et enregistre le serveur MCP
astroglia install          # simulation : affiche exactement ce qui va changer
astroglia install --yes
```

Redémarrez Claude Code. `astroglia doctor` vérifie l'installation ; `astroglia ui` ouvre l'interface.

## L'interface

| | |
|---|---|
| ![Context Monitor](docs/images/context-monitor.png) **Context Monitor.** Ce que le routeur a choisi ou écarté pour une tâche, avec le détail du score, et ce qui a été servi à Claude. | ![Fiche projet](docs/images/project-card.png) **Projets.** La fiche, les index et chaque connaissance mémorisée, avec les fichiers exacts qui ont changé. |
| ![Galaxie](docs/images/galaxy-selected.png) **Galaxie.** Chaque étoile est une entrée stockée, chaque ligne une relation stockée. Sélectionnez une étoile pour voir ses relations, leur type et leur sens ; Maj+clic sur une deuxième pour tracer le chemin. Les impulsions ne suivent que de vrais événements. | ![Tableau de bord](docs/images/dashboard.png) **Tableau de bord.** Ce qu'Astroglia a réellement fait (compté) et économisé (estimé, avec la formule). |

Aussi : **Neural** (parcourir le graphe), **Clusters** (un plugin ou un projet à la fois), **Timeline** (ce qui a été appris, modifié, est devenu périmé, jour par jour), **Health** (score de santé, relations suggérées, mémoires qui se chevauchent, outils jamais utilisés, zones faibles), **Memory** (modifier, fusionner, relier, restaurer n'importe quelle version).

## Mesures

Choix des outils, sur une installation réelle (74 capacités, 22 tâches annotées dans `bench/local-tasks.json`) :

| | top 1 | top 3 | ressources attendues retrouvées | résultats par tâche |
|---|---|---|---|---|
| BM25 seul | 0,82 | 0,82 | n/a | toutes les correspondances |
| Astroglia `route` | 0,82 | **0,86** | 0,79 | **4,0** (~324 tokens, estimés) |

Scénarios de valeur (`python bench/value.py <dossier-demo>`) :

| Scénario | Sans Astroglia | Fichier de notes + recherche par mot-clé | Astroglia |
|---|---|---|---|
| Retrouver la solution passée pour 4 questions (démo) | tout refaire | bonne note trouvée 1/4 | **trouvée en premier 4/4** |
| Savoir quelles notes sont dépassées (démo, 2 périmées) | n/a | 0 signalée | **2 signalées** |
| S'orienter dans 9 projets réels (tokens, estimés) | 41 145 (18 lectures) | n/a | **2 157** avec les fiches complètes (9 lectures), **326** avec la seule ligne du manifeste (0 lecture) |

La référence « sans » parcourt toute l'arborescence et lit README et manifestes une fois ; un agent plus économe lirait moins, le gain réel se situe entre les deux. Sur de tout petits projets, une fiche complète peut coûter plus que les fichiers eux-mêmes : c'est la ligne du manifeste qui fait toujours gagner.

Charge (`python bench/load.py`) : routage sur 20 500 entrées en 43 ms ; vérification de fraîcheur de 500 entrées inchangées en 71 ms (989 ms avant) ; la galaxie affiche 20 000 étoiles et 40 000 relations à environ 70 images/s.

## Confidentialité et sécurité

- Tout est local (`~/.astroglia/astroglia.db`). Aucune télémétrie, aucun appel réseau.
- Lecture seule sur la configuration de Claude Code, sauf `astroglia install` / `uninstall`, qui sauvegardent `settings.json` d'abord.
- `remember` refuse ce qui ressemble à un secret. Tout ce qu'Astroglia renvoie est étiqueté comme donnée, jamais comme instruction.
- L'interface n'écoute que sur 127.0.0.1, avec une clé par lancement.
- Les hooks ne bloquent jamais Claude Code : en cas de panne, il démarre normalement.

## Limites

- Astroglia **recommande** ; Claude décide quoi charger.
- Les tokens sont des estimations (≈ 4 caractères par token).
- La recherche est lexicale : les synonymes sans mot commun peuvent être manqués.
- Les fiches projet listent des faits issus des manifestes ; elles n'expliquent pas l'architecture.

La documentation complète (configuration, commandes, architecture) est en anglais : [README.md](README.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Contributions bienvenues : [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Apache-2.0
