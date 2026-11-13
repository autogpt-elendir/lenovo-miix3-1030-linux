# Son : Bay Trail, RT5640 et SOF

Le but est de retrouver un profil audio utilisable après réinstallation sans
recopier l’état privé de la session ou changer au hasard le routage du codec.
Le haut-parleur, le casque et le microphone ont chacun leur propre recette.

## État constaté sur la tablette de référence

| Élément | Valeur constatée |
| --- | --- |
| Modèle | Lenovo MIIX 3-1030, produit 80HV |
| Carte ALSA | SOF, `sof-bytcht rt5640` |
| Firmware DSP | SOF 2.2.0 |
| Topologie active | `sof-byt-rt5640-ssp0.tplg` |
| UCM | `alsa-ucm-conf` 1.2.15.3 |
| Serveur audio | PipeWire 1.6.2, WirePlumber 0.5.13 |
| Sortie reconnue | profil HiFi, périphérique Speaker |
| Entrée reconnue | microphone présent dans la pile audio |
| Validation acoustique | **en attente de confirmation humaine** |

Ces informations prouvent la détection de la pile et des routes audio, pas
encore l’émission physique par le haut-parleur. Un retour de lecture réussi
ne suffit pas à écrire « son validé ». Le casque et l’enregistrement ne sont
pas validés par la simple présence de leurs profils.

## Dépendances et configuration d’origine

Sur Ubuntu/Lubuntu 26.04, conserver les paquets de distribution :

- `alsa-utils` pour les outils ALSA ;
- `alsa-ucm-conf` pour les profils et séquences du codec ;
- `firmware-sof-signed` pour le firmware et les topologies SOF ;
- PipeWire et WirePlumber fournis/configurés par le bureau.

Le paquet Ubuntu de firmware comprend `intel/sof/sof-byt.ri`,
`intel/sof-tplg/sof-byt-rt5640.tplg` et sa variante `-ssp0.tplg`.
L’énumération du noyau détermine laquelle employer : ne pas remplacer une
variante par l’autre uniquement parce que son nom semble plus générique.
[Contenu officiel du paquet Ubuntu](https://packages.ubuntu.com/resolute/all/firmware-sof-signed/filelist).

Pour le driver ALSA `SOF`, la sélection UCM passe par
`ucm2/conf.d/SOF/SOF.conf`, puis `Intel/SOF/HiFi.conf`. Le nom de carte
`bytcht rt5640` sélectionne le profil RT5640 ; ses composants indiquent les
routes Speaker, Headphones et Mic. Il n’est pas nécessaire d’inventer un
répertoire UCM portant le nom complet de la carte.
[Source UCM SOF](https://github.com/alsa-project/alsa-ucm-conf/blob/master/ucm2/Intel/SOF/HiFi.conf),
[profil RT5640](https://github.com/alsa-project/alsa-ucm-conf/blob/master/ucm2/Intel/bytcr-rt5640/HiFi.conf).

Ne pas publier ni recopier un `/var/lib/alsa/asound.state`, un profil
WirePlumber ou une configuration de session venant d’une autre tablette.
Le dépôt ne redistribue pas de firmware : il s’appuie sur les paquets de
l’OS, leur provenance et leurs licences.

## Vérification sans modifier le son

Exécuter depuis le compte de la session graphique, **sans sudo** :

```bash
python3 scripts/audio_check.py
```

Le JSON conserve seulement le modèle attendu, une indication de compatibilité,
la présence du Speaker RT5640, son identifiant dynamique, son volume et son
état muet. Il ne publie ni l’inventaire PipeWire brut, ni les noms personnels,
ni une adresse réseau. Il ne capture aucun microphone et n’émet aucun son.

Depuis SSH, employer le même compte que le bureau et son environnement de
session. Si `XDG_RUNTIME_DIR` manque, il peut être indiqué pour cette commande :

```bash
XDG_RUNTIME_DIR="/run/user/$(id -u)" python3 scripts/audio_check.py
```

Si aucune sortie attendue n’apparaît, vérifier d’abord :

```bash
cat /proc/asound/cards
aplay -l
wpctl status
systemctl --user status pipewire wireplumber
```

Les sorties détaillées de ces outils restent locales ; ne pas les publier
sans les relire, car des noms de session ou d’applications peuvent y figurer.
Une carte absente demande l’examen des journaux noyau et des fichiers de
firmware avant de changer les volumes.

## Sélection explicite du haut-parleur

```bash
python3 scripts/audio_check.py --select-speaker
```

Cette option est volontaire : elle choisit le Speaker HiFi interne par son
identifiant courant, réduit un volume supérieur à 35 %, puis le démutifie si
nécessaire. Un volume déjà inférieur à 35 % reste inchangé. Si son niveau est
nul, l’augmenter prudemment dans l’interface du bureau : le script ne le fait
pas automatiquement.

L’action refuse un autre modèle, un codec différent, une sortie casque, un
profil Pro Audio, un identifiant ambigu ou une exécution comme root. Le nom
exact de la sortie, le type ALSA et la carte SOF RT5640 doivent tous correspondre.
L’identifiant numérique PipeWire n’est jamais fixé dans la configuration.

## Signal court et confirmation humaine

Prévenir la personne devant la tablette, puis exécuter :

```bash
python3 scripts/audio_check.py --test
```

Ou, pour sélectionner le Speaker avant le test :

```bash
python3 scripts/audio_check.py --select-speaker --test
```

Le test génère un signal de 880 Hz pendant 0,75 seconde, S16_LE, stéréo,
48 kHz, à faible amplitude avec une rampe au début et à la fin. `pw-play`
vise explicitement la sortie Speaker, sans enregistrer le microphone.
La lecture seule de test ne change ni le périphérique par défaut ni son volume ;
le fichier WAV temporaire unique est supprimé même si la lecture échoue.
Si son chemin a été remplacé par un lien ou un autre fichier, il est conservé
plutôt que de risquer une suppression étrangère au test.

Un haut-parleur muet, un niveau nul ou une amplification supérieure à 100 %
font refuser le test ; il faut modifier cet état explicitement. La sélection
et la lecture ont un délai maximal. Un résultat
`software_playback_completed: true` signifie que le logiciel a terminé la
lecture ; `acoustic_confirmation: required` demande encore une écoute humaine.

Recette physique à consigner séparément :

1. Signal entendu dans le haut-parleur, sans casque branché.
2. Lecture brève au casque et détection du branchement/débranchement, si testé.
3. Microphone vérifié par une prise de parole volontaire ; ne pas enregistrer
   l’ambiance automatiquement ou publier une capture personnelle.
4. Même fonctionnement après redémarrage.

Ne cocher que les points réellement observés.

## Limites connues et sources

Linux 7.0 ne possède pas de quirk DMI spécifique au MIIX 3-1030 dans le pilote
`bytcr_rt5640`. Celui du MIIX 3-830 ne s’applique pas automatiquement à ce modèle.
Le code examine le routage BIOS, puis le paramètre de la carte. Toute valeur
`quirk=` forcée doit donc venir d’une preuve matérielle et d’un essai avec
retour arrière, pas d’un guide pour un autre appareil.
[Source du pilote](https://github.com/torvalds/linux/blob/v7.0/sound/soc/intel/boards/bytcr_rt5640.c).

Le sélecteur DSP Intel emploie `0=auto`, `2=SST`, `3=SOF`. Le mode `1=legacy`
n’est pas pris en charge par le chemin ACPI Bay Trail. Un repli SST constitue
une expérience distincte seulement si le diagnostic démontre un échec SOF ;
il ne doit pas remplacer la pile détectée par défaut dans ce dépôt.
[Source du sélecteur Linux 7.0](https://github.com/torvalds/linux/blob/v7.0/sound/hda/core/intel-dsp-config.c).

Bay Trail utilise la branche de maintenance SOF `stable-v2.2`. Les fichiers
anciens peuvent manquer dans un checkout récent de `sof-bin` ; les paquets
Ubuntu ou les archives de publication complètes conviennent mieux qu’un
installateur Git générique. Aucun correctif audio particulier entre les
noyaux Ubuntu `7.0.0-38` et `-42` n’est établi ici sans recette matérielle.
[Plateformes SOF](https://thesofproject.github.io/latest/platforms/index.html),
[précautions du dépôt sof-bin](https://github.com/thesofproject/sof-bin/blob/main/README.md).

## Tests du dépôt

```bash
python3 tests/test_audio_check.py -v
python3 scripts/audio_check.py --help
python3 -m py_compile scripts/audio_check.py tests/test_audio_check.py
```

Les tests utilisent des mocks : ils ne jouent aucun son et ne capturent pas
le microphone. Ils vérifient notamment le filtrage des métadonnées, les gardes
modèle/codec/profil, le plafond de volume, le WAV et son nettoyage ciblé.
