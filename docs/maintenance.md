# Maintenance, mises à jour et retour arrière

## Contrôler le résultat de l'installation

Sur la tablette :

```bash
uname -r
systemctl status miix-internal-wifi.service --no-pager
sudo /usr/local/libexec/miix-internal-wifi status
nmcli device status
python3 scripts/audio_check.py
```

Conserver la connexion USB de secours pour la première recette. Vérifier une
connexion fraîche par la carte interne, puis un accès réseau en liant la
commande à son interface. Les noms d'interface doivent être lus sur cette
installation plutôt que copiés d'un ancien inventaire.

Le reçu `/var/lib/miix3-1030/wifi-build.json` permet de relier le module
installé à sa construction. Sources, patches et empreintes sont dans
`profiles/` et `patches/`. Ne pas publier ses fichiers privés d'inventaire,
les profils NetworkManager ou les profils/cookies du navigateur.

## Changement de noyau

La qualification Wi-Fi porte sur **`7.0.0-42-generic`**. Le service et le helper
refusent un noyau différent. Le dépôt ne fournit pas de promesse DKMS universelle
et n'installe pas de gel des mises à jour.

Le module utilise des structures privées du cœur SDHCI. Une compilation
réussie ou un `vermagic` correspondant ne suffit pas à démontrer leur
compatibilité. Le builder vérifie les sources épinglées et génère des
assertions de taille et de position des champs depuis le BTF du noyau exécuté.

Avant de dépendre d'un nouveau noyau :

1. Garder un noyau de secours démarrable, une sauvegarde adaptée et un accès
   réseau USB. Vérifier le chargeur EFI IA32 et l'espace disponible.
2. Vérifier les changements des sources noyau/Ubuntu et les en-têtes privés
   SDHCI, puis adapter les références, empreintes et gardes de version du dépôt.
3. Construire et tester sur ce noyau : contrôle matériel, ABI, module sans
   alias automatique, retour arrière et contrôleur de stockage inchangé.
4. Refaire association, trafic, redémarrage et son avant d'étendre la
   qualification. Conserver un échec ou une validation partielle dans le suivi.

Ne pas simplement remplacer la constante de version pour franchir le garde.
Ne pas réassocier ou décharger globalement `sdhci_acpi` : il peut porter
l'eMMC système en même temps que le Wi-Fi.

## Reconstruire le module qualifié

Le builder doit s'exécuter comme utilisateur normal disposant des droits de
lecture requis pour BTF et les sources :

```bash
python3 scripts/build_wifi.py --check
python3 scripts/build_wifi.py build --work-dir "$HOME/miix-wifi-build-new"
```

Choisir un répertoire encore inexistant. La compilation est limitée à un job,
avec priorité réduite et durée bornée. Le résultat est un JSON avec le chemin
et l'empreinte du module, le noyau et le nombre d'assertions ABI. Le journal
`build.log` et `build-result.json` restent dans le répertoire de construction.
La compilation séparée ne remplace pas les contrôles d'installation du playbook.

## Désactiver le contournement Wi-Fi

Préparer une console locale ou un accès réseau de secours avant cette action :

```bash
sudo systemctl disable --now miix-internal-wifi.service
sudo /usr/local/libexec/miix-internal-wifi status
```

L'arrêt du service réassocie uniquement le contrôleur Wi-Fi à `sdhci-acpi`
et remet le module radio stock. Sur le matériel qui nécessite le correctif,
le réseau interne peut alors redevenir indisponible. Les fichiers du module
peuvent rester installés sans effet : ne pas effacer un pilote système ou
un fichier préexistant pour tenter un retour arrière.

Sur un noyau différent, le helper gardé refuse aussi l'opération ; redémarrer
sur le noyau qualifié avec l'accès de secours avant de manipuler ce contrôleur.
Le retour logiciel ne peut pas réparer un blocage total du noyau.

## Vérifier l'alimentation

Un branchement direct du chargeur libère la tablette du partage OTG si son
Wi-Fi interne est opérationnel. Pour un statut de charge, comparer deux
relevés frais de `charge_now`, horodatés et espacés, avec la tablette dans
les mêmes conditions. `Charging` seul n'établit pas un gain net ; près de la
pleine charge, `Not charging` et une valeur stable peuvent être cohérents
avec la fin du cycle. Le courant de batterie ne mesure pas le courant du
chargeur. Aucun suivi périodique n'est créé par les outils de ce dépôt.
