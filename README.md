# MisteR Dashboard

Créé et maintenu par [Yann ROBERT](https://github.com/YannRobert)

Tableau de bord local des MR ouvertes d'un projet GitLab — par défaut `group/project` —,
avec les signaux CI (pipeline, Sonar, PIT, threads, retard sur la cible) et des notifications
navigateur.

`server.py` sert la page (`index.html`) et relaie les appels GitLab et Sonar, pour garder les tokens
hors du navigateur. Il n'écoute que sur `127.0.0.1`.

## Prérequis

- `~/.config/glab-cli/config.yml` authentifié contre `gitlab.example.com` (celui de `glab`).
- `SONAR_TOKEN` dans l'environnement du shell qui lance le serveur. Sans lui, les pastilles Sonar
  restent grises.

## Lancer le serveur — toujours détaché

Le serveur doit survivre à la session qui l'a lancé. Lancé en tâche de fond d'une session Claude Code,
il est **tué au bout de 2 h** ; lancé au premier plan d'un terminal, il meurt avec ce terminal. On le
détache donc avec `setsid nohup`, via le lanceur :

```bash
scripts/mr-dashboard/start.sh              # profil back (ce dépôt)
scripts/mr-dashboard/start.sh <profil>     # autre projet, cf. § Suivre un autre projet
```

Il ne lance rien si le profil tourne déjà ou si son port est pris, attend que la page réponde en
`200`, puis affiche l'URL ; en cas d'échec, il affiche la fin du journal. Les options passées après
le profil sont transmises à `server.py` et l'emportent sur celles du profil
(`start.sh back --port 9100`).

| Action | Commande |
|---|---|
| Vérifier qu'il répond | `curl -s --max-time 2 -o /dev/null -w '%{http_code}\n' http://localhost:8765/` (attendu : `200`) |
| Consulter le journal | `tail -f ~/.local/state/mr-dashboard-<profil>.log` |
| Arrêter un profil | `scripts/mr-dashboard/stop.sh <profil>` |
| Tout arrêter | `scripts/mr-dashboard/stop.sh` |

Le serveur ne survit pas à un redémarrage de WSL : le relancer avec `start.sh`.

## Suivre un autre projet

Tout ce qui est propre au projet suivi vient d'un **profil**, `profiles/<nom>.conf`, que
`profiles/back.conf` documente variable par variable. Pour un autre projet (le front par exemple),
le copier sous un autre nom, l'adapter — **avec un autre `PORT`** pour faire tourner les deux
ensemble — puis `start.sh <nom>`.

- `server.py` n'a **aucun défaut qui désigne un projet** : une variable requise oubliée arrête le
  démarrage (le journal dit laquelle), au lieu de faire suivre ce dépôt-ci en silence.
- Un projet **sans mutation testing** ou **sans Sonar** le déclare : `PIT_ENABLED=false`,
  `SONAR_ENABLED=false`. Les colonnes correspondantes disparaissent, ni leurs données ni leurs
  notifications ne sont chargées, et le prompt de correction ne réclame plus ces indicateurs.
- `TARGET_BRANCH` fixe la branche cible filtrée à l'ouverture (vide : toutes les cibles).
- Le prompt de correction cite `scripts/mr-ci-signals.py` de ce dépôt par son chemin absolu, avec les
  options du projet suivi (`--no-pit`, `--no-sonar`, `--pit-marker` compris) : son clone n'a pas ce
  script.

## Ouvrir le dashboard

**http://localhost:8765/** dans le navigateur Windows (WSL relaie `localhost`).

- Pour recevoir les notifications, cocher **Notifications** dans l'en-tête et accepter la demande du
  navigateur. Sur ses propres MR, la notification reste affichée et revient toutes les 15 minutes tant
  qu'un problème reste ouvert.
- Une nouvelle approbation d'une MR est notifiée aussi, sauf celle qu'on a donnée soi-même. **Sons**, à côté,
  indépendant des notifications : cloche de bar quand sa MR est approuvée ou qu'on approuve celle
  d'un autre (à la mise à jour suivante), un tintement quand un autre l'approuve, deux notes graves sur un nouveau problème bloquant de sa MR ; cocher la case fait entendre la
  cloche. Après un rechargement, le navigateur ne laisse jouer un son qu'après un clic ou une touche dans
  la page.
- `?lang=en` pour forcer l'anglais.
- Recharger la page ne sollicite ni GitLab ni git : elle réaffiche les données sauvegardées dans le
  navigateur et n'interroge GitLab que si l'actualisation des 5 minutes est due, comptées depuis la
  dernière, d'où qu'elle vienne (autre onglet compris). Le serveur ne fetch que si une page lui signale
  un état des MR qu'il n'a jamais vu : une sauvegarde rejouée, ou celle, plus ancienne, d'un autre
  navigateur, ne relance rien. **Rafraîchir** et **git fetch** partent toujours.
- Le texte grandit avec la largeur de la fenêtre : à 100 % de zoom, le tableau tient sur tout écran.
  **A− / A+**, dans l'en-tête, l'ajustent de 70 à 150 % (retenu dans le navigateur, repris par la page
  de diff) ; préférer ce réglage au zoom du navigateur, qui vaut pour tous les onglets du dashboard.
- **Ouvertes | Mergées**, dans l'en-tête : la vue des MR mergées (`?view=merged`) relit l'histoire des
  MR fermées sur une période de merge (7, 30 — par défaut —, 90 jours ou toutes), pour comprendre
  après coup pourquoi certaines ont duré. Ni pipeline, ni qualité, ni retard : durée totale,
  développement (premier commit → dernier push) et stabilisation (dernier push → merge), en temps
  calendaire. Le volet d'activité des commits s'y arrête au merge. Chargée à la demande, par paquets
  de 50 au fil du défilement — toute la période dès qu'on trie sur une autre colonne que la date de
  merge —, elle n'est ni sauvegardée, ni actualisée automatiquement, ni notifiée.
- **Requêtes GitLab · 1 / 5 / 15 min**, dans l'en-tête : ce que le serveur a envoyé à GitLab, API et
  `git fetch`, sur la dernière minute et les 5 et 15 dernières, tous onglets confondus — le navigateur
  ne parle jamais à GitLab en direct. Au clic, un tableau : lectures, écritures et fetch par fenêtre,
  total, erreurs (connexion, 4xx, 5xx, git fetch), cumul et moyenne par minute depuis le démarrage du serveur, et Sonar à part ; en
  orange, une erreur hors 4xx dans les 5 dernières minutes. Pour vérifier que le dashboard ne surcharge pas GitLab.

### Aucune notification ne s'affiche

Cocher la case envoie aussitôt « 🔔 Notifications MisteR Dashboard activées ». Si elle n'apparaît pas,
c'est le navigateur ou Windows qui bloque, pas le dashboard :

1. autorisation du site : icône à gauche de l'URL → *Notifications* → *Autoriser* ;
2. Windows : *Paramètres → Système → Notifications* → le navigateur doit être activé, et
   *Ne pas déranger* (ou l'*Assistant de concentration*) désactivé ;
3. décocher puis recocher la case pour renvoyer la notification de test.

## Actions AI

Le bouton **AI** d'une MR ouverte propose les actions du catalogue du projet suivi : le dialogue
affiche le prompt de l'action choisie, à copier dans Claude Code ou à lancer dans un onglet Orca (quand
le serveur tourne dans WSL et qu'Orca est installé). Le bouton porte un liseré rouge quand la MR a
quelque chose à corriger : branche en retard ou en conflit, indicateur qualité imparfait, thread non
résolu.

Le même bouton figure en haut du diff d'une MR ouverte, avec les mêmes actions : de quoi demander une
explication en lisant le diff, puis poser ses questions dans la session ouverte. La correction n'y est
proposée que si un onglet du dashboard a mis ses données à jour dans la demi-heure : seul le dashboard
charge les indicateurs CI et les threads dont son prompt est fait.

Le catalogue est le fichier `.mr-dashboard/ai-actions.toml`, commité à la racine du projet suivi et lu
dans son worktree principal. Il est relu à chaque ouverture du dialogue : un prompt modifié s'essaie
sans redémarrer ni commiter. Une action par bloc `[[action]]`, dans l'ordre du dialogue :

```toml
[[action]]
id = "…"           # unique dans le fichier
label = "…"        # libellé du choix dans le dialogue
tab = "… !{iid}"   # titre de l'onglet Orca (défaut : label)
when = "to-fix"    # facultatif : seulement quand la MR a quelque chose à corriger
prompt = """
…
"""
```

Variables du prompt : `{iid}`, `{title}`, `{source_branch}`, `{target_branch}`, `{web_url}`, et
`{fix_context}`, le prompt de correction calculé par le dashboard (mise à jour de la branche,
indicateurs imparfaits, threads, boucle de vérification jusqu'à des indicateurs parfaits). Une
variable inconnue reste telle quelle dans le prompt affiché.

Sans catalogue, seule la correction est proposée, avec `{fix_context}` pour prompt. Un catalogue
invalide n'en propose aucune : le dialogue dit pourquoi.

## Dépôt local : fetch et diff

Le serveur agit sur le clone local du projet (`REPO_DIR`, ce dépôt par défaut), toujours dans son
**worktree principal**, d'où qu'il soit lancé.

- **Fetch** : `git fetch --prune origin` toutes les 5 minutes (`GIT_FETCH_INTERVAL`, en secondes, `0`
  pour aucun), même sans page ouverte, et dès que la page voit une MR recevoir des commits, apparaître
  ou disparaître, ou la branche du pipeline avancer. La case **Fetch auto** de l'en-tête suspend ces
  fetchs automatiques, pour le serveur donc pour tous les onglets, jusqu'à ce qu'on la recoche ou que
  le serveur redémarre. Tout fetch, même manuel ou sur changement, relance les 5 minutes ; comme pour
  l'actualisation auto, une barre sous la case montre le temps qui reste avant le prochain. Le bouton
  **git fetch** lance un fetch tout de suite ; à côté, l'heure du
  dernier fetch, ou son échec en rouge (le survol donne le message de git et l'heure du dernier fetch
  réussi). Les `origin/<branche>` restent ainsi à jour pendant une coupure
  de GitLab : on peut relire et committer, puis pousser à son retour.
- **diff** : chaque MR ouverte a un bouton qui affiche dans un nouvel onglet son diff depuis le point
  où elle part de sa cible (`git diff origin/<cible>...origin/<branche>`, comme l'onglet *Changes* de
  GitLab), calculé sur le dépôt local : il reste disponible pendant une coupure de GitLab. Une MR
  mergée, même ancienne et sa branche supprimée, a le sien, retrouvé par ses commits
  (`git diff <merge commit>^1...<dernier commit>`) ; une tête absente du clone, après un squash, vient
  de `refs/merge-requests/<iid>/head`. Ni worktree ni branche locale : un simple `git diff`. Au-dessus
  des fichiers, les commits de la MR (sans ceux de la cible qu'elle a mergée) : un clic n'affiche que
  ce commit, Maj+clic étend jusqu'à un autre (`git diff <premier>^1 <dernier>`), **Tout** revient au
  diff complet ; la plage est dans l'adresse. Les commits sont groupés par push, d'après les versions
  de la MR dans GitLab (sans GitLab, pas de groupes) : un clic sur un push, ou **Dernier push**, n'affiche
  que les commits arrivés avec lui. **Nouveaux (n)** n'affiche que les commits arrivés depuis la dernière
  lecture de ce diff dans le navigateur, numéros en couleur dans la liste.
  La poignée entre la liste des commits et celle des fichiers règle leur répartition (retenue par le
  navigateur) ; un double-clic la rétablit. Une plage qui contient un merge de la cible le signale :
  son diff montre aussi ce que ce merge a apporté. Liste des
  fichiers dans un panneau latéral toujours visible (nom, puis répertoire ; le fichier lu y est
  surligné ; largeur réglable par son coin bas droit), côte à côte ou ligne à ligne (retenu dans le
  navigateur), coloration syntaxique, thème du dashboard. Texte à la taille de celui du dashboard, réglage
  A− / A+ de celui-ci compris, plus 25 % par défaut, ajustable de 80 à 300 % par ses propres **A− / A+**
  (retenu dans le navigateur) : le zoom du navigateur vaut pour tout `localhost:8765` et
  agrandirait aussi le dashboard. Au-delà de 5 Mo
  de diff, la page renvoie vers GitLab. L'affichage vient de
  [diff2html](https://github.com/rtfpessoa/diff2html) (MIT), copié dans `vendor/diff2html/` pour
  marcher sans réseau ; pour le mettre à jour, y remplacer `diff2html-ui-slim.min.js` et
  `diff2html.min.css` par ceux de `https://cdn.jsdelivr.net/npm/diff2html@<version>/bundles/`.
- **💬 Diff notes**, dans l'en-tête du diff, affiche les diff notes GitLab de la MR sous les lignes
  commentées, résolues repliées. Une note posée sur un code qui a changé depuis, ou hors de la plage de
  commits affichée, va dans « diff notes hors du diff affiché », en tête du diff. **‹ ›** passent d'une
  diff note à la suivante. Désactivé — par défaut, choix retenu par le navigateur —, la page ne charge
  rien de plus ; les commandes gardent leur place quel que soit son état.
- **🗨 Commentaires** — dans l'en-tête du diff, ou à côté de **diff** dans le dashboard — ouvre dans un
  onglet `comments.html`, les commentaires de la MR qui ne portent sur aucune ligne (rapports PIT,
  Sonar, Trivy, revues…), avec leurs réponses. Commentaires et diff notes sont rendus comme dans
  GitLab, d'après le HTML que GitLab en donne (`notes.js`, `notes.css`), débarrassé de tout ce qui
  pourrait s'exécuter dans la page.
  Les 30 dernières MR consultées y restent sauvegardées dans le navigateur : à la réouverture, la
  sauvegarde s'affiche aussitôt (« commentaires du 08/10/2026 à 10:42 · mise à jour en cours… ») puis
  laisse la place à la réponse de GitLab. GitLab lent (15 s) ou indisponible — maintenance, serveur
  arrêté —, la sauvegarde reste affichée, bandeau orange ; Répondre et Résoudre attendent GitLab.
- Un onglet par page et par MR : un lien vers le diff ou les commentaires d'une MR déjà ouverts — depuis
  le dashboard, le diff ou les commentaires — ramène à leur onglet et le recharge, pour ne jamais
  montrer une version périmée de la MR (`tabs.js`) ; la plage de commits et le défilement de l'onglet
  repartent de zéro. Le clic du milieu et Ctrl+clic ouvrent toujours un nouvel onglet.
- L'en-tête du diff et des commentaires indique quand la page a été chargée (« chargée à 14:32 · il
  y a 5 min », la date en plus si c'était un autre jour), mis à jour chaque minute et en orange
  au-delà de 30 min : F5 pour voir les derniers changements de la MR.
- **✕ Fermer**, dans l'en-tête du diff et des commentaires, ferme l'onglet sans confirmation du
  navigateur. Celui-ci ne laisse fermer qu'un onglet ouvert depuis le dashboard ou un lien ; pour un
  onglet ouvert à la main, le bouton devient « Ctrl+W ».
- Diff notes affichées, sur tout le diff (sans plage de commits) et un clone local à jour du dernier
  push : un clic sur un numéro de ligne ouvre un éditeur dessous, Maj+clic l'étend à une plage ;
  **Publier dans GitLab** (Ctrl+Entrée) y crée la discussion.
- Au bas de chaque fil, commentaire comme diff note, **Répondre** ouvre une réponse à publier dans
  GitLab (Ctrl+Entrée, Échap pour annuler), et **Résoudre** ou **Rouvrir** change son état ; le fil est
  aussitôt relu dans GitLab et réaffiché à sa place.
- Ce sont les seules écritures du serveur dans GitLab, sur une MR du projet suivi : `/gitlab/discussion`
  ne transmet qu'un commentaire de ligne, `/gitlab/reply` une réponse à un fil, `/gitlab/resolve` son
  état résolu ou non.
- **GitLab injoignable** : une MR dont la mise à jour échoue garde ses derniers bons signaux, marqués
  « Signaux anciens » (date et cause au survol). Nombre de commits, date du dernier commit et retard sur
  la cible viennent alors du clone local, en gris italique, quand GitLab n'en a rien donné ou que le
  dernier fetch est plus récent que ses données (`git_actions.py`, `/git/branch`) ; la date est celle du
  commit, le clone ne sachant pas quand il a été poussé. Le volet d'activité des commits prend alors
  ses commits du clone (`/git/commits`) et ses commentaires de la dernière ouverture du volet sur cette
  MR, gardés dans le navigateur.
- Un `git fetch` ou `git pull` lancé à la main pendant un fetch automatique peut répondre
  « cannot lock ref » : le relancer.

## Après une modification

- `index.html`, `diff.html` et les fichiers qu'ils chargent (`ai.js`, `notes.js`…) sont relus à chaque
  requête : recharger la page suffit. Un nouveau fichier s'ajoute à `STATIC_FILES` de `server.py`.
- `server.py`, `orca_launcher.py`, `ai_actions.py` ou `git_actions.py` : `stop.sh` puis `start.sh`, ou
  `systemctl --user restart mr-dashboard@<profil>` si le serveur tourne en service systemd (`CLAUDE.md`).
- Le serveur sert l'`index.html` du dépôt (ou du worktree) d'où il a été lancé : pour tester la
  version d'un worktree, relancer le serveur depuis ce worktree.
