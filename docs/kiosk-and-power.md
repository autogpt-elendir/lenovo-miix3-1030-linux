# Kiosque, mémoire et alimentation

Ces options adaptent la tablette à un écran de suivi. Elles restent
**désactivées par défaut**. Le matériel Wi-Fi/audio se prépare d'abord,
puis les options sont activées dans le fichier local de variables.

## Navigateur plein écran

Exemple dans `vars.local.yml` :

```yaml
miix_user: tabletuser
miix_kiosk_enabled: true
miix_kiosk_url: https://dashboard.example.invalid/
```

Remplacer l'URL par celle de son service. Éviter tout mot de passe ou jeton
dans l'URL. L'authentification du service se fait manuellement dans le navigateur ;
les cookies et le profil doivent rester locaux à la tablette.

Le kiosque utilise Falkon, un profil dédié et l'unité utilisateur
`miix-kiosk.service`. Une session graphique ouverte et le bus systemd
utilisateur sont nécessaires. La configuration du dépôt évite de restaurer
plusieurs onglets à chaque démarrage et utilise `--current-tab` pour la
navigation dans l'instance existante. Le plein écran ne constitue pas un
verrouillage de sécurité du poste.

Après application, vérifier la page réellement affichée, la session et le
tactile. Une unité `active` ou un HTTP 200 ne prouve pas que le dashboard est
visible et authentifié.

## Désactiver explicitement la veille LXQt

```yaml
miix_disable_idle_sleep: true
```

Cette option modifie la politique de gestion d'énergie LXQt du compte choisi.
La laisser à `false` conserve le choix habituel de l'utilisateur. Après sa
modification, rouvrir la session si nécessaire et vérifier la configuration
effective de LXQt, de l'économiseur d'écran et de DPMS.

Le bouton Power et le Wake-on-LAN n'ont pas fourni un cycle fiable de veille
et reprise sur la machine historique. Un écran de suivi permanent doit donc
être alimenté et sa politique de veille choisie explicitement. Le dépôt ne
masque pas les protections matérielles contre batterie vide ou surchauffe.
Le turbo CPU n'est pas désactivé : aucun changement de fréquence ou nombre
de cœurs n'est appliqué implicitement avec le kiosque.

## Garde mémoire optionnel de Falkon

```yaml
miix_kiosk_enabled: true
miix_kiosk_url: https://dashboard.example.invalid/
miix_kiosk_memory_guard_enabled: true
```

Le garde utilisateur observe toutes les 15 secondes le cgroup de
`miix-kiosk.service`, y compris ses renderers. Si sa RAM et son swap cumulés
restent strictement au-dessus de 2 Gio pendant 60 secondes d'observations
continues, il demande le redémarrage de ce seul navigateur. Le délai minimal
entre demandes est 600 secondes. Un trou d’observation supérieur à 30 secondes
annule la fenêtre de dépassement. La relance vise uniquement une unité déjà
active, avec son identité et ses compteurs recontrôlés. Le timer utilisateur
s’appelle `miix-kiosk-memory-guard.timer`. Son état technique temporaire est privé ;
il ne conserve pas de capture, d'URL visitée ou de contenu de page.

Ce mécanisme compense une croissance mémoire. Il n'établit ni ne corrige la
cause d'une fuite, et peut être retardé si le système est déjà bloqué. Ne pas
le remplacer par un redémarrage de la tablette dès le premier octet de swap.
La relance reprend la page de démarrage gérée ; une session web expirée peut
nécessiter une nouvelle connexion manuelle.

La recette générique et ses tests doivent être validés sur la nouvelle
installation ; les observations historiques d'une autre configuration de
kiosque ne prouvent pas son affichage ou sa stabilité sur ce nouveau profil.

Pour arrêter le seul garde dans la session utilisateur :

```bash
systemctl --user disable --now miix-kiosk-memory-guard.timer
```

## Swap Btrfs optionnel

```yaml
miix_swap_enabled: true
```

L'option ajoute un espace de swap de 2 Gio dans un sous-volume dédié
`/swap-miix`, fichier `/swap-miix/swapfile`. Elle exige Btrfs et au moins 3 Gio
d’espace libre avant création, dont 1 Gio conservé comme réserve, utilise la méthode native Btrfs sans CoW, et ajoute une entrée fstab
avec `nofail`. Les swaps déjà actifs sont conservés. Un chemin préexistant
non géré ou ambigu provoque un refus ; il ne faut pas l'effacer pour forcer
l'application.

Avant de l'activer :

```bash
findmnt -no FSTYPE,SOURCE --target /
swapon --show --bytes
free -h
```

Sur un autre système de fichiers, conserver ou configurer son swap avec la
méthode adaptée ; cette option ne convertit pas les partitions. Le swap
n'ajoute pas de RAM et peut augmenter les entrées/sorties de l'eMMC. Le
sous-volume portant un swap actif doit être exclu des snapshots.
[Contraintes officielles Btrfs](https://btrfs.readthedocs.io/en/latest/Swapfile.html).

## Valider l'alimentation en usage réel

Avec le Wi-Fi interne opérationnel, retirer le réseau USB temporaire et
brancher le chargeur directement au micro-USB. Comparer deux lectures
actuelles de la charge de batterie pendant l'affichage habituel. Le statut
`Charging`, la puissance indiquée sur le chargeur et un pourcentage isolé ne
suffisent pas à établir le bilan net.

Relever ensuite mémoire, swap, réactivité et consommation dans les conditions
réelles du dashboard. Aucune autonomie, performance vidéo ou absence durable
de gel n'est déduite des seuls tests unitaires.
