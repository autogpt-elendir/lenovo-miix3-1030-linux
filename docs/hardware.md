# Matériel pris en charge et résultats établis

## Modèle de référence

- Lenovo MIIX 3-1030, type DMI `80HV`, Intel Atom Z3735F.
- CPU x86-64, firmware UEFI 32 bits, environ 2 Gio de RAM et eMMC 58 Gio.
- Écran 1920×1200, bureau LXQt/X11 sur l'installation qualifiée.
- Unique micro-USB partagé entre charge et données.

Ce dépôt garde des vérifications matérielles strictes : il ne revendique pas
la compatibilité de toutes les tablettes Bay Trail ou de tous les modèles MIIX.
Une autre variante doit être identifiée et qualifiée séparément.

## Wi-Fi interne et stockage

La puce est une Realtek RTL8723BS SDIO `024c:b723`. Son contrôleur est le
périphérique de plateforme `INT33BB:00`, ACPI `INT33BB`, UID 2. Le correctif
limite ce contrôleur au mode SDIO legacy à 25 MHz **avant** détection de la carte.
Le DMA est conservé. Le pilote radio `r8723bs` et le firmware Ubuntu restent
utilisés.

Une baisse de fréquence après initialisation n'avait pas suffi. La variante
retenue se lie manuellement au seul contrôleur Wi-Fi, sans alias de capture
automatique. Les contrôleurs eMMC continuent d'utiliser `sdhci-acpi`.
L'identité de la racine est déterminée dynamiquement ; les indices `mmc` et
`mmcblk` ne doivent pas servir de garde matérielle.

La machine de référence a passé association, DHCP, ping, accès LAN/HTTPS,
redémarrage et test avec le réseau USB déconnecté. Une fois le dongle et le hub
retirés, la recharge directe avec Wi-Fi interne a été mesurée positive ;
la batterie a ensuite atteint 99 %. Cela ne garantit pas les performances de
n'importe quel chargeur ou câble.

## Audio

La pile observée est SOF sur Bay Trail avec le codec RT5640 et la carte
`sof-bytcht rt5640`, liaison SSP0, firmware SOF 2.2.0 et profil UCM Speaker.
Versions de paquets relevées lors de la qualification :

| Paquet | Version observée |
| --- | --- |
| `alsa-ucm-conf` | `1.2.15.3-1ubuntu1.7` |
| `firmware-sof-signed` | `2025.12.2-1` |
| `pipewire` | `1.6.2-1ubuntu1.2` |
| `wireplumber` | `0.5.13-1ubuntu1.1` |

Ces versions décrivent l'installation observée, pas un verrouillage de tous
les paquets. La détection de la pile et d'une route Speaker est établie ;
**l'audition physique des haut-parleurs reste à confirmer**. Le test du dépôt
a terminé avec succès côté logiciel : signal stéréo S16LE à 48 kHz pendant
0,75 s vers la route Speaker du RT5640, sans captation et sans modifier le
volume observé à 40 % ou l’état non muet. Un code retour réussi ne démontre
pas à lui seul que le haut-parleur a émis un son audible.

La recette audio
n'impose pas un changement arbitraire SOF/SST ni un quirk de codec.

## Housse-clavier et écran tactile

La housse officielle avec clavier/pavé tactile s'identifie comme USB Lenovo
`17ef:606e`. Elle est distincte du périphérique I²C ITE8568 et du contrôleur
tactile ELAN1001. La remise en contact du folio a rétabli clavier et pavé sur
la machine de référence ; les pilotes USB HID et libinput étaient déjà liés.
Aucun pilote particulier n'a été nécessaire pour cette réparation.

Si la housse devient muette, vérifier sa présence USB et remettre ses contacts
en place avant d'ajouter une option noyau. Ne pas capturer de saisie privée
pour un diagnostic. Après installation, vérifier physiquement frappe, pavé,
toucher et orientation ; la détection des périphériques ne prouve pas les gestes.

## Limites encore ouvertes

La webcam OV2722 n'est pas qualifiée. Le réveil réseau à travers un adaptateur
USB n'a pas été fiabilisé ; l'envoi d'un paquet magique n'en prouve pas le
succès. La stabilité graphique, la consommation et le son doivent être
observés avec les applications réellement utilisées.

[Guide matériel officiel Lenovo](https://download.lenovo.com/consumer/mobiles_pub/lenovo_miix_3_1030_hmm_201605.pdf).
