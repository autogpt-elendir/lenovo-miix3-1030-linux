# Lenovo MIIX 3-1030 sous Linux

Guide et configuration reproductible pour remettre une **Lenovo MIIX 3-1030
(type 80HV)** sous **Lubuntu/Ubuntu 26.04 amd64**, avec son firmware UEFI
32 bits, le Wi-Fi interne et la pile audio Linux.

Le dépôt conserve les correctifs utiles à cette machine et leurs contrôles.
Le parcours complet sur un système fraîchement réinstallé n’a pas été rejoué ;
les constructions, diagnostics et lectures de test sont qualifiés séparément.
L'installation du système sur l'eMMC reste une opération manuelle : choisir
le disque, les partitions et le compte dans l'installateur, après sauvegarde.

## État de validation

| Élément | État établi |
| --- | --- |
| Système de référence | Ubuntu 26.04.1 / LXQt, noyau `7.0.0-42-generic` |
| Amorçage | UEFI 32 bits, système et processeur 64 bits ; chargeur GRUB IA32 requis |
| Wi-Fi RTL8723BS | Connexion, DHCP, trafic LAN/HTTPS et redémarrage vérifiés sur la machine de référence |
| Recharge | Recharge nette vérifiée avec Wi-Fi interne et chargeur directement sur micro-USB |
| Audio | SOF/RT5640 et route Speaker détectés ; lecture logicielle du test du dépôt réussie, audition physique encore à confirmer |
| Housse-clavier | Fonctionnement confirmé après remise en contact ; pilote USB standard |
| Tactile | Contrôleur ELAN1001 détecté ; contrôle physique des gestes à refaire après installation |
| Kiosque et protections mémoire | Options désactivées par défaut ; recettes et tests du dépôt, nouvelle installation à valider |
| Webcam | Fonctionnement non qualifié |

Le correctif Wi-Fi est **qualifié pour ce noyau exact**. Il doit être
reconstruit et vérifié pour tout autre noyau. Voir les
[limites matérielles](docs/hardware.md) et la [maintenance](docs/maintenance.md).

## Parcours de réinstallation

1. Suivre [l'installation et l'amorçage IA32](docs/installation.md) : ISO
   officielle, clé USB, installation manuelle, puis noyau et dépendances.
2. Préparer un contrôleur **Ubuntu 24.04 ou 26.04, Python 3.12 à 3.14**, puis
   ses fichiers locaux. Le pin Ansible fourni ne prend pas en charge le Python
   3.10 par défaut d’Ubuntu 22.04 :

   ```bash
   sudo apt-get install python3-venv
   python3 -m venv .venv
   . .venv/bin/activate
   python3 -m pip install -r requirements.txt
   cp --no-clobber ansible/inventory.example.ini inventory.local.ini
   cp --no-clobber ansible/vars.example.yml vars.local.yml
   ```

   Adapter l'adresse, `ansible_user` et `miix_user` au compte créé sur la
   tablette. Garder ces fichiers locaux hors Git. Le compte doit être un
   utilisateur normal disposant de `sudo`.
   Pour un pilotage distant, préparer OpenSSH et valider l’accès par clé selon
   [le guide d’installation](docs/installation.md) avant de lancer Ansible.
3. Vérifier puis appliquer la recette depuis une machine avec Ansible :

   ```bash
   ansible-galaxy collection install -r ansible/requirements.yml
   ansible-playbook -i inventory.local.ini ansible/playbook.yml \
     -e @vars.local.yml --ask-become-pass --check
   ansible-playbook -i inventory.local.ini ansible/playbook.yml \
     -e @vars.local.yml --ask-become-pass
   ```

   Le playbook construit le module Wi-Fi depuis les sources épinglées,
   contrôle son ABI, installe le service de démarrage et les paquets audio.
   Il ne configure pas le mot de passe Wi-Fi. Utiliser l'interface graphique
   ou `nmcli --ask` sur la tablette.
4. Contrôler le Wi-Fi et suivre [la recette audio](docs/audio.md), puis
   redémarrer en gardant un accès réseau USB de secours pour la première
   validation. Confirmer le réseau et le son après ce redémarrage.

Pour exécuter Ansible directement sur la tablette, créer un inventaire local
contenant le groupe `[miix]` et un hôte `tablet ansible_connection=local`.
Le compte `miix_user` reste obligatoire. Un inventaire `localhost,` seul ne
correspond pas au groupe du playbook.

## Construction et diagnostic Wi-Fi séparés

```bash
python3 scripts/build_wifi.py --check
python3 scripts/build_wifi.py build --work-dir "$HOME/miix-wifi-build"
sudo python3 scripts/internal_wifi.py status
```

Le répertoire de construction doit être neuf. Le résultat JSON donne
`module_path`, `module_sha256`, `kernel` et `abi_assertions`. La construction
n'installe rien ; le playbook réalise l'installation contrôlée.

## Options d'usage

Le [guide kiosque et alimentation](docs/kiosk-and-power.md) décrit l'affichage
plein écran, la désactivation explicite de la veille, le swap Btrfs et le
garde mémoire optionnels. Le turbo CPU n'est pas modifié par cette recette.

Les sources Linux et les correctifs sont référencés par version et empreinte
dans `profiles/`. Les paquets et firmwares audio proviennent des dépôts Ubuntu.
Les détails de l'installation privée ayant servi à la qualification sont
remplacés par des exemples à renseigner localement.
