# MisteR Dashboard

Créé et maintenu par [Yann ROBERT](https://github.com/YannRobert)

Tableau de bord local des MR ouvertes du projet `group/project`, avec les signaux CI
(pipeline, Sonar, PIT, threads, retard sur la cible) et des notifications navigateur.

`server.py` sert la page (`index.html`) et relaie les appels GitLab et Sonar, pour garder les tokens
hors du navigateur. Il n'écoute que sur `127.0.0.1`.

## Prérequis

- `~/.config/glab-cli/config.yml` authentifié contre `gitlab.example.com` (celui de `glab`).
- `SONAR_TOKEN` dans l'environnement du shell qui lance le serveur. Sans lui, les pastilles Sonar
  restent grises.

## Lancer le serveur — toujours détaché

Le serveur doit survivre à la session qui l'a lancé. Lancé en tâche de fond d'une session Claude Code,
il est **tué au bout de 2 h** ; lancé au premier plan d'un terminal, il meurt avec ce terminal. On le
détache donc avec `setsid nohup`, depuis la racine du dépôt :

```bash
mkdir -p ~/.local/state
pgrep -af mr-dashboard/server.py \
  || setsid nohup python3 scripts/mr-dashboard/server.py \
       > ~/.local/state/mr-dashboard.log 2>&1 < /dev/null & disown
```

Le `pgrep` évite d'en lancer un second : le port serait déjà pris.

| Action | Commande |
|---|---|
| Vérifier qu'il répond | `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8765/` (attendu : `200`) |
| Consulter le journal | `tail -f ~/.local/state/mr-dashboard.log` |
| Arrêter | `pkill -f mr-dashboard/server.py` |
| Autre port | ajouter `--port 9100` à la commande de lancement |

Le serveur ne survit pas à un redémarrage de WSL : le relancer avec la même commande.

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
- `server.py` ou `orca_launcher.py` : arrêter puis relancer le serveur.
- Le serveur sert l'`index.html` du dépôt (ou du worktree) d'où il a été lancé : pour tester la
  version d'un worktree, relancer le serveur depuis ce worktree.
