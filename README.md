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
- `TARGET_BRANCH` fixe la branche cible filtrée à l'ouverture (vide : `PIPELINE_BRANCH`) — `main`
  pour un projet sans `develop`.
- Le prompt de correction cite `scripts/mr-ci-signals.py` de ce dépôt par son chemin absolu, avec les
  options du projet suivi (`--no-pit`, `--no-sonar`, `--pit-marker` compris) : son clone n'a pas ce
  script.

## Ouvrir le dashboard

**http://localhost:8765/** dans le navigateur Windows (WSL relaie `localhost`).

- Pour recevoir les notifications, cocher **Notifications** dans l'en-tête et accepter la demande du
  navigateur. Sur ses propres MR, la notification reste affichée et revient toutes les 15 minutes tant
  qu'un problème reste ouvert.
- `?lang=en` pour forcer l'anglais.
- Recharger la page ne sollicite ni GitLab ni git : elle réaffiche les données sauvegardées dans le
  navigateur et n'interroge GitLab que si l'actualisation des 5 minutes est due, comptées depuis la
  dernière, d'où qu'elle vienne (autre onglet compris). Le serveur ne fetch que si l'état des MR a changé
  depuis le dernier qu'une page lui a signalé. **Rafraîchir** et **git fetch** partent toujours.
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

### Aucune notification ne s'affiche

Cocher la case envoie aussitôt « 🔔 Notifications MisteR Dashboard activées ». Si elle n'apparaît pas,
c'est le navigateur ou Windows qui bloque, pas le dashboard :

1. autorisation du site : icône à gauche de l'URL → *Notifications* → *Autoriser* ;
2. Windows : *Paramètres → Système → Notifications* → le navigateur doit être activé, et
   *Ne pas déranger* (ou l'*Assistant de concentration*) désactivé ;
3. décocher puis recocher la case pour renvoyer la notification de test.

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
  agrandirait aussi le dashboard. On répond aux discussions dans GitLab, à un clic. Au-delà de 5 Mo
  de diff, la page renvoie vers GitLab. L'affichage vient de
  [diff2html](https://github.com/rtfpessoa/diff2html) (MIT), copié dans `vendor/diff2html/` pour
  marcher sans réseau ; pour le mettre à jour, y remplacer `diff2html-ui-slim.min.js` et
  `diff2html.min.css` par ceux de `https://cdn.jsdelivr.net/npm/diff2html@<version>/bundles/`.
- **💬 Diff notes**, dans l'en-tête du diff, affiche les diff notes GitLab de la MR sous les lignes
  commentées, résolues repliées. Une note posée sur un code qui a changé depuis, ou hors de la plage de
  commits affichée, va dans « diff notes hors du diff affiché », en tête du diff. **‹ ›** passent d'une
  diff note à la suivante. **🗨 Commentaires** affiche à part, en tête du diff, les commentaires de la
  MR qui ne portent sur aucune ligne. Désactivés — par défaut, choix retenus par le navigateur —, ils
  ne chargent rien de plus ; les commandes gardent leur place quel que soit leur état.
- Diff notes affichées, sur tout le diff (sans plage de commits) et un clone local à jour du dernier
  push : un clic sur un numéro de ligne ouvre un éditeur dessous, Maj+clic l'étend à une plage ;
  **Publier dans GitLab** (Ctrl+Entrée) y crée la discussion. C'est la seule écriture du serveur dans
  GitLab : l'action `/gitlab/discussion` ne transmet qu'un commentaire de ligne sur une MR du projet
  suivi.
- Un `git fetch` ou `git pull` lancé à la main pendant un fetch automatique peut répondre
  « cannot lock ref » : le relancer.

## Après une modification

- `index.html` et `diff.html` sont relus à chaque requête : recharger la page suffit.
- `server.py`, `orca_launcher.py` ou `git_actions.py` : `stop.sh` puis `start.sh`.
- Le serveur sert l'`index.html` du dépôt (ou du worktree) d'où il a été lancé : pour tester la
  version d'un worktree, relancer le serveur depuis ce worktree.
