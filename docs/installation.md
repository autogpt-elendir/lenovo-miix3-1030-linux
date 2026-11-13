# Installer Lubuntu sur la MIIX 3-1030

## Préparer le matériel et les sauvegardes

Cette procédure vise la **MIIX 3-1030 / 80HV**, CPU Intel Atom Z3735F, UEFI
32 bits. Vérifier le modèle sous le pied ou dans le firmware. L'architecture
amd64 de l'ISO concerne le système ; elle ne signifie pas que le firmware
peut lancer un exécutable EFI 64 bits.

Sauvegarder les données et la configuration de l'ancien système avant de
modifier ses partitions. Prévoir une clé USB, un adaptateur OTG et un accès
réseau USB temporaire compatible. La tablette n'a qu'un micro-USB partagé
entre charge et périphériques : partir avec une batterie chargée et contrôler
l'alimentation pendant l'installation. Un hub alimenté ne garantit pas la
recharge de la tablette en mode hôte.

## 1. Télécharger une ISO officielle

Télécharger Lubuntu 26.04 LTS amd64 et ses sommes de contrôle depuis
[l'archive officielle Lubuntu](https://cdimage.ubuntu.com/lubuntu/releases/26.04/release/).
Vérifier le SHA256 de l'image téléchargée et l'authenticité du fichier des
sommes selon la procédure Ubuntu. Choisir le bureau LXQt pour rester proche
de la configuration de référence.

Préparer une clé dont le contenu de l'ISO est accessible sur une partition
FAT32, avec les dossiers `casper`, `boot/grub` et `EFI`. Le choix et le
formatage de la clé sont manuels. Identifier sa capacité et son modèle,
sauvegarder son contenu, puis utiliser l'outil de préparation approprié.
Aucune commande de ce dépôt ne sélectionne ou ne formate un disque.

## 2. Ajouter le chargeur de démarrage UEFI 32 bits

L'ISO utilisée pour la qualification nécessitait l'ajout de
`EFI/BOOT/BOOTIA32.EFI`. Vérifier le contenu de l'image choisie ; conserver les
chargeurs 64 bits déjà présents.

Sur une machine Debian/Ubuntu disposant des outils GRUB :

```bash
sudo apt-get install grub-efi-ia32-bin grub-common
python3 scripts/build_bootia32.py --output "$HOME/bootia32.efi"
```

Le fichier de sortie doit être absent avant la commande. Le programme génère
une image GRUB `i386-efi` et une configuration embarquée recherchant
`/casper/vmlinuz`, puis chargeant le `boot/grub/grub.cfg` du support trouvé.
Le paramètre `-p /boot/grub` seul n'est pas présenté comme une recherche de
support : c'est la configuration embarquée qui accomplit cette recherche.

Copier ensuite manuellement ce fichier vers `EFI/BOOT/BOOTIA32.EFI` sur la
clé FAT32. Si un fichier de ce nom existe déjà, l'identifier et en conserver
une copie avant de décider de le remplacer. Éjecter proprement la clé.

Cette image est destinée à la disposition d'une clé Lubuntu avec `casper`.
Pour une autre distribution ou une ISO dont les chemins changent, adapter
la configuration et refaire un test de démarrage avant toute installation.

## 3. Démarrer et installer manuellement

Ouvrir le menu de démarrage de la tablette avec ses boutons physiques ;
selon son état, le menu Novo se rejoint avec Volume+ et Power. Sélectionner
le support USB. Le chargeur IA32 produit ici n'est pas signé pour Secure Boot :
la procédure de référence utilise Secure Boot désactivé.

Dans la session live, vérifier l'affichage, le tactile et la saisie avant
l'installation. Un clavier USB externe peut servir si les contacts du folio
sont instables. Pour la housse, commencer par détacher/reclipser ses contacts.

Dans l'installateur, identifier l'eMMC par sa capacité et sa topologie. Une
lecture utile est :

```bash
lsblk -o NAME,SIZE,MODEL,TRAN,FSTYPE,MOUNTPOINTS
```

Les noms `mmcblk` et les numéros d'hôtes peuvent changer ; aucun nom de disque
n'est une cible universelle. Choisir les partitions et l'éventuel remplacement
de l'ancien système dans l'installateur, en vérifiant son récapitulatif final.
Créer un utilisateur normal, par exemple `tabletuser`, et lui permettre `sudo`.

### Vérifier le chargeur installé sur l'eMMC

Avant de retirer le support de secours, vérifier que l'installation possède
un chargeur EFI IA32. Si l'installateur n'a pas posé le bon chargeur, les
commandes suivantes sont destinées à **l'installation Linux neuve démarrée**,
avec sa partition EFI déjà identifiée et montée sur `/boot/efi` :

```bash
cat /sys/firmware/efi/fw_platform_size
findmnt -no SOURCE,FSTYPE,TARGET /boot/efi
sudo apt-get install grub-efi-ia32 grub-efi-ia32-bin
sudo grub-install --target=i386-efi --efi-directory=/boot/efi --bootloader-id=Linux
sudo update-grub
```

La première lecture doit indiquer 32 et le montage EFI doit correspondre à la
partition FAT de cette installation. Ne pas exécuter ces commandes dans un
chroot dont les montages n'ont pas été préparés. Sur un système avec d'autres
OS, préserver leurs fichiers EFI et vérifier les entrées existantes avant
toute modification. Redémarrer et valider le démarrage sur eMMC avec la clé
USB retirée.

### Secours : l'installation sur eMMC ne démarre pas

Redémarrer sur la clé live IA32, choisir l'essai de Lubuntu et conserver le
réseau temporaire. Cette section répare le chargeur de **l'installation déjà
présente**, sans formater de partition. Elle ne constitue pas un test de
réinstallation fraîche effectué par le projet.

Identifier de nouveau les partitions :

```bash
lsblk -o PATH,PKNAME,TYPE,SIZE,FSTYPE,PARTTYPE,PARTUUID,LABEL,MOUNTPOINTS
sudo blkid
cat /sys/firmware/efi/fw_platform_size
read -r -p "Partition racine Linux installée : " ROOT_PART
read -r -p "Partition EFI de cette installation : " ESP_PART
unset ROOT_FS RESCUE
test -b "$ROOT_PART" && test -b "$ESP_PART" &&
test "$ROOT_PART" != "$ESP_PART" &&
test "$(sudo blkid -s TYPE -o value -- "$ESP_PART")" = vfat &&
ROOT_FS=$(sudo blkid -s TYPE -o value -- "$ROOT_PART") &&
printf 'Type de la racine sélectionnée : %s\n' "$ROOT_FS" &&
RESCUE=$(sudo mktemp -d /mnt/miix-rescue.XXXXXX)
```

La taille de firmware doit être 32. Vérifier visuellement que `ROOT_PART` et
`ESP_PART` appartiennent à l'eMMC visée, et non au support live ou à un autre
disque. L'ESP doit être la partition EFI FAT de cette installation, pas une
partition de données ayant simplement le même système de fichiers. Si la
racine est chiffrée, ouvrir d'abord son conteneur avec la procédure appropriée
et sélectionner le périphérique bloc Linux déchiffré ; cette recette ne
prépare pas automatiquement ce cas.

**Choisir une seule des deux méthodes de montage suivantes**, selon le type
lu et la disposition effectivement installée :

- **Racine ext4** :

  ```bash
  test "$ROOT_FS" = ext4 && sudo mount "$ROOT_PART" "$RESCUE"
  ```

- **Racine Btrfs** : inspecter d'abord les sous-volumes en lecture seule,
  puis monter le sous-volume racine confirmé. L'exemple `@` est à utiliser
  uniquement si la liste et l'installation le confirment :

  ```bash
  test "$ROOT_FS" = btrfs &&
  sudo mount -o ro,subvolid=5 "$ROOT_PART" "$RESCUE" &&
  sudo btrfs subvolume list "$RESCUE"
  ```

  Si la liste confirme que `@` est la racine installée, poursuivre :

  ```bash
  sudo umount "$RESCUE" && sudo mount -o subvol=@ "$ROOT_PART" "$RESCUE"
  ```

Arrêter si le système de fichiers ou le sous-volume ne correspond pas à ces
cas. Vérifier ensuite que le montage est bien la racine Linux attendue,
puis ajouter l'ESP et les vues système du live :

```bash
(
  set -e
  test -n "$RESCUE"
  mountpoint -q "$RESCUE"
  sudo test -f "$RESCUE/etc/os-release"
  sudo cat "$RESCUE/etc/os-release"
  sudo mkdir -p "$RESCUE/boot/efi"
  sudo mount "$ESP_PART" "$RESCUE/boot/efi"
  findmnt -no SOURCE,FSTYPE,TARGET "$RESCUE/boot/efi"
  for tree in dev proc sys run; do
    sudo mount --rbind "/$tree" "$RESCUE/$tree"
    sudo mount --make-rslave "$RESCUE/$tree"
  done
  sudo chroot "$RESCUE" /bin/bash
)
```

Les montages `--rbind` incluent les sous-montages nécessaires, dont `dev/pts` :
ne pas créer une seconde vue `devpts`. `--make-rslave` évite qu'un démontage
ultérieur de ces vues se propage au système live.

Dans le shell chroot, vérifier le montage EFI une dernière fois puis installer
le chargeur 32 bits :

```bash
findmnt -no SOURCE,FSTYPE,TARGET /boot/efi
apt-get update
apt-get install grub-efi-ia32 grub-efi-ia32-bin
grub-install --target=i386-efi --efi-directory=/boot/efi --bootloader-id=Linux --recheck
update-grub
```

Le réseau et la résolution DNS du live doivent fonctionner ; la vue `/run`
permet de suivre les chemins de résolution utilisés par l'installation.
Un échec réseau doit être corrigé avant de réessayer APT.

`grub-install` écrit les fichiers EFI et tente de mettre à jour l'entrée de
démarrage NVRAM. Sur un firmware qui refuse ou oublie cette entrée, le mode
amovible ci-dessous installe le chemin de repli `EFI/BOOT/BOOTIA32.EFI` sans
mise à jour NVRAM. **C'est une écriture EFI supplémentaire à choisir
explicitement**, après inspection des fichiers déjà présents :

```bash
if [ -e /boot/efi/EFI/BOOT/BOOTIA32.EFI ]; then
  ls -l /boot/efi/EFI/BOOT/BOOTIA32.EFI
  sha256sum /boot/efi/EFI/BOOT/BOOTIA32.EFI
fi
```

Si ce fichier existe, en conserver une copie avec un nom neuf sur un support
de sauvegarde, contrôler son empreinte et identifier son propriétaire avant
de décider de son remplacement. Ne pas utiliser le repli pour écraser un
chargeur d'un autre OS ou un fichier inconnu. Une fois ce choix confirmé :

```bash
grub-install --target=i386-efi --efi-directory=/boot/efi --bootloader-id=Linux --no-nvram --removable
update-grub
```

Quitter le chroot avec `exit` et attendre le retour à la session live. Démonter
ensuite **uniquement** les vues de ce secours, dans l’ordre inverse. Fermer
d’abord tout autre terminal ayant son répertoire de travail dans ce montage :

```bash
case "$RESCUE" in
  /mnt/miix-rescue.*)
    sudo umount --recursive "$RESCUE/run" &&
    sudo umount --recursive "$RESCUE/sys" &&
    sudo umount --recursive "$RESCUE/proc" &&
    sudo umount --recursive "$RESCUE/dev" &&
    sudo umount "$RESCUE/boot/efi" &&
    sudo umount "$RESCUE" &&
    sudo rmdir "$RESCUE"
    ;;
  *) printf 'Refus : chemin de secours absent ou inattendu.\n' >&2 ;;
esac
```

Si un démontage est occupé, examiner `findmnt --submounts "$RESCUE"` et fermer
les utilisateurs de ce seul montage ; ne pas forcer un démontage global.
Redémarrer ensuite avec la clé retirée et valider le démarrage sur eMMC.

## 4. Préparer le noyau qualifié et les outils

Le système de référence est Ubuntu 26.04.1 avec
`7.0.0-42-generic` / paquets Ubuntu `7.0.0-42.42`. Vérifier d'abord leur
présence dans les dépôts configurés :

```bash
sudo apt-get update
apt-cache policy linux-image-7.0.0-42-generic linux-headers-7.0.0-42-generic
```

Installer les paquets noyau exacts disponibles, avec leurs dépendances :

```bash
sudo apt-get install linux-image-7.0.0-42-generic linux-modules-7.0.0-42-generic linux-headers-7.0.0-42-generic
sudo apt-get install gcc-15 make patch kmod linux-tools-7.0.0-42-generic
sudo apt-get install linux-firmware-realtek alsa-utils alsa-ucm-conf firmware-sof-signed pipewire pipewire-pulse wireplumber
```

Le manifeste `profiles/kernel-packages.json`, lorsqu'il est utilisé pour
conserver ces artefacts, référence les paquets et empreintes de la qualification.
Les versions exactes peuvent quitter un miroir courant : dans ce cas, arrêter
et établir une nouvelle source/qualification vérifiée. Ne pas faire accepter
un autre noyau au helper en changeant seulement une constante.

Redémarrer sur le noyau qualifié puis vérifier :

```bash
uname -r
cat /sys/firmware/efi/fw_platform_size
python3 scripts/build_wifi.py --check
```

Le noyau doit être exactement `7.0.0-42-generic`. La vérification Wi-Fi doit
confirmer le matériel, les outils, les en-têtes et les métadonnées BTF requis.
Les dépendances de firmware chargées par le système doivent rester celles
des paquets Ubuntu ; ne pas remplacer les fichiers SOF/SST au hasard.

## 5. Appliquer la recette du dépôt

Le contrôleur Ansible doit disposer de Python 3.12 à 3.14, comme Ubuntu 24.04
ou 26.04. Le Python 3.10 habituel d’Ubuntu 22.04 ne convient pas au pin Ansible
2.20.11 du dépôt. Installer le support venv avant de créer l’environnement :

```bash
sudo apt-get install python3-venv
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Le support venv apporte `ensurepip` ; une installation globale de pip n’est
pas nécessaire.

### Préparer l'accès SSH depuis un autre ordinateur

Pour piloter Ansible à distance, installer OpenSSH sur la tablette et démarrer
le serveur. L'exécution Ansible locale peut utiliser `ansible_connection=local`
comme décrit dans le README :

```bash
sudo apt-get install openssh-server
sudo systemctl enable --now ssh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Noter l'empreinte affichée sur la console de la tablette et la comparer lors
de la première connexion. Sur le contrôleur, choisir une clé **publique**
existante et adapter le compte et l'adresse avant copie :

```bash
ssh-copy-id -i "$HOME/.ssh/id_ed25519.pub" tabletuser@tablet.local
ssh -o BatchMode=yes -o PreferredAuthentications=publickey tabletuser@tablet.local 'id -un; hostname'
```

Garder la clé privée sur le contrôleur et charger sa phrase secrète dans son
agent si nécessaire. Aucun fichier de clé privée, mot de passe ou profil de
connexion réel ne doit être ajouté au dépôt. Vérifier aussi que le compte
possède `sudo` ; la recette demande son mot de passe avec `--ask-become-pass`.

Ouvrir et vérifier **deux sessions par clé indépendantes** avant d'envisager
une désactivation des mots de passe SSH. Ce dépôt n'applique pas ce
changement automatiquement. Renseigner ensuite le compte et l'adresse
vérifiés dans les fichiers locaux d'inventaire et de variables.

Suivre le parcours Ansible du [README](../README.md), avec l'accès réseau USB
de secours encore disponible. Le playbook construit le module comme
l'utilisateur choisi, conserve son résultat dans
`/var/lib/miix3-1030/wifi-build.json` et installe le service
`miix-internal-wifi.service`. Le build de diagnostic peut aussi être lancé
séparément avec `scripts/build_wifi.py build --work-dir <répertoire-neuf>`.

Configurer le réseau Wi-Fi dans LXQt ou avec `nmcli --ask`. Une clé Wi-Fi
ne doit pas être écrite dans un inventaire Git ou un argument de commande.

Pour l'audio, ouvrir la session graphique de l'utilisateur puis suivre
[le diagnostic et le test des haut-parleurs](audio.md). La présence d'une
carte ALSA n'est pas une preuve d'émission audible.

La recette refuse un module déjà présent qu'elle ne possède pas : sur une
machine déjà corrigée, commencer par les diagnostics et la simulation.
Ne pas effacer les fichiers de l'autre installation pour contourner ce refus.

## 6. Recette finale

Après redémarrage, contrôler le service, la connexion et le son. Tester ensuite
la carte interne avec la liaison de secours déconnectée, en gardant un moyen
local de revenir en arrière. Le chargeur peut alors être branché directement
au micro-USB. Comparer deux lectures de `BATC/charge_now` espacées : le statut
`Charging` seul n'établit pas une recharge nette.

Le parcours complet de cette procédure n’a pas été exécuté sur une eMMC
fraîchement réinstallée ; les tests publiés concernent les constructions, la
recette et les périphériques de la machine de référence.

La stabilité sur une journée, la veille/reprise et les gestes tactiles
nécessitent une observation réelle ; les résultats de la machine de référence
ne remplacent pas cette recette après réinstallation.
