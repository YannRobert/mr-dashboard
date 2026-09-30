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

Tout ce qui est propre au projet suivi vient d'un **profil**, `profiles/<nom>.conf` : projet GitLab,
clé Sonar, noms des jobs Sonar et PIT, marqueur de la note de mutation, port, et clone local où le
bouton de correction ouvre Orca. `profiles/back.conf` documente chaque variable ; pour un autre projet
(le front par exemple), le copier sous un autre nom, l'adapter — **avec un autre `PORT`** pour faire
tourner les deux ensemble — puis `start.sh <nom>`.

- Un job absent du pipeline du projet (pas de mutation testing, par exemple) laisse simplement la
  pastille correspondante grise.
- Le prompt de correction cite `scripts/mr-ci-signals.py` de ce dépôt par son chemin absolu, avec les
  options du projet suivi : son clone n'a pas ce script.

## Ouvrir le dashboard

**http://localhost:8765/** dans le navigateur Windows (WSL relaie `localhost`).

- Pour recevoir les notifications, cocher **Notifications** dans l'en-tête et accepter la demande du
  navigateur. Sur ses propres MR, la notification reste affichée et revient toutes les 15 minutes tant
  qu'un problème reste ouvert.
- `?lang=en` pour forcer l'anglais.

### Aucune notification ne s'affiche

Cocher la case envoie aussitôt « 🔔 Notifications MisteR Dashboard activées ». Si elle n'apparaît pas,
c'est le navigateur ou Windows qui bloque, pas le dashboard :

1. autorisation du site : icône à gauche de l'URL → *Notifications* → *Autoriser* ;
2. Windows : *Paramètres → Système → Notifications* → le navigateur doit être activé, et
   *Ne pas déranger* (ou l'*Assistant de concentration*) désactivé ;
3. décocher puis recocher la case pour renvoyer la notification de test.

## Après une modification

- `index.html` est relu à chaque requête : recharger la page suffit.
- `server.py` ou `orca_launcher.py` : `stop.sh` puis `start.sh`.
- Le serveur sert l'`index.html` du dépôt (ou du worktree) d'où il a été lancé : pour tester la
  version d'un worktree, relancer le serveur depuis ce worktree.
