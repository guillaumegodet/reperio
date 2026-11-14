# Repério : localiser une revue dans les BU françaises pour le PEB

Repério (*repérer* + *périodique*) est une preuve de concept. Elle répond à une question : pour une revue et une année, où la trouver ? Elle enchaîne quatre étapes, chacune correspondant à une phase du plan.

0. **Fonds de Nantes Université (étape 0).** Elle vérifie d'abord si Nantes Université donne déjà accès à l'année demandée (abonnement, archives, Licence nationale activée, bouquet libre), d'après l'export du catalogue Nantilus. Si oui, pas de PEB.
1. **Accès sans PEB (phase 2).** Elle cherche si l'année est en libre accès (OpenAlex, DOAJ), couverte par une Licence nationale (BACON) ou présente dans ISTEX.
2. **Sudoc (phase 1).** Elle lit les états de collection papier et électronique déclarés dans le Sudoc.
3. **Résolveurs (phase 3).** Elle interroge les résolveurs de liens des BU prioritaires.

## Lancer

Les scripts utilisent uniquement la bibliothèque standard de Python, sans paquet à installer.

```
python peb_nantes.py --indexer chemin/vers/export_hlm_nantilus.csv   # une fois, puis à chaque nouvel export
python reperio.py demandes_poc.csv
```

Sans index, l'étape 0 est sautée et le rapport le signale.

Le script produit deux fichiers :

- `resultats_reperio.csv` : le tableau complet, séparé par des points-virgules, à ouvrir dans Excel ou Grist ;
- `rapport_reperio.html` : une page à ouvrir dans un navigateur. Elle présente un verdict par demande, les localisations triées par confiance, et des filtres pour n'afficher que les BU prioritaires ou masquer les localisations douteuses.

Le fichier de demandes est séparé par des points-virgules et contient trois colonnes : `libelle;issn;annee`.

- **ISSN :** un seul suffit. Le script retrouve seul l'autre support et les titres précédents ou suivants.
- **Année :** une seule (`2016`), plusieurs (`2016 2018`) ou une plage (`2016-2018`).

Options :

- `--issn 0008-6568 --annee 2016` : traiter une demande directement, sans fichier ;
- `--sans-hopitaux` : exclure les centres hospitaliers ;
- `--sans-cache` : ignorer le cache. Par défaut, les réponses sont gardées une semaine dans `.cache_sudoc/`.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `reperio.py` | Enchaîne les quatre étapes et produit le CSV et le rapport HTML |
| `peb_nantes.py` | Fonds électroniques de Nantes Université, d'après l'export HLM du catalogue Nantilus |
| `peb_sudoc.py` | Sudoc : états de collection, liens entre supports et titres, codes PEB de la zone 930 $j |
| `peb_acces.py` | Libre accès, Licences nationales, ISTEX |
| `peb_resolveurs.py` | Résolveurs Alma des BU prioritaires |
| `resolveurs.csv` | Table de configuration des résolveurs, une ligne par BU prioritaire |
| `bu-prio.csv` | Liste des BU prioritaires transmise par l'équipe PEB |

## Fonds de Nantes Université : l'export HLM de Nantilus

Le catalogue Nantilus repose sur la base de connaissances EBSCO. Son export brut « Holdings Management » (HLM, un CSV d'environ 300 Mo) décrit, bouquet par bouquet, la couverture électronique de chaque titre. C'est le même fichier que celui de l'onglet « Revues » du tableau de bord de Druid : une seule mise à jour sert les deux outils.

`python peb_nantes.py --indexer export.csv` en garde les seules revues (environ 58 000 lignes, 77 000 ISSN) dans `donnees/fonds_nantes.json.gz`, un fichier de 2 Mo lu en moins d'une seconde. Ce dossier est ignoré par git : le dépôt est public, l'export n'y a pas sa place. Le chemin peut être changé avec la variable `REPERIO_INDEX_NANTES`.

Règles appliquées :

- la couverture saisie par Nantes Université (`CustomCoverage*`, `CustomEmbargo`) passe avant celle d'EBSCO ;
- les titres masqués (`HideOnPublicationFinder`) ou supprimés (`Delete`) sont ignorés ;
- l'année est contrôlée sur chaque plage de couverture (une ligne peut en avoir plusieurs, séparées par « | »), embargo compris ;
- la nature de l'accès se déduit du nom du bouquet et du champ local `UserDefinedField4` : Licence nationale (« ISTEX », « Licences nationales », « LN »), libre accès (DOAJ, PubMed Central, Gallica, bouquets « Open Access »…), archives pérennes, agrégateur (`AggregatedFullText`), sinon abonnement.

| Confiance | Cas |
| --- | --- |
| haute | Bouquet qui couvre toute l'année : la demande s'arrête là |
| moyenne | Année couverte en partie (début ou fin de plage, embargo), ou agrégateur dont des articles peuvent manquer |
| faible | Titre présent à Nantes, mais pas pour l'année demandée |

Autres commandes :

```
python peb_nantes.py --etat                          # date de l'export, nombre de titres
python peb_nantes.py --issn 0002-9343 --annee 1998   # une demande, sans le reste de la chaîne
```

Le rapport affiche la date de l'export et signale un export de plus de 120 jours.

## Tester les résolveurs

Pour vérifier que les résolveurs répondent toujours (à lancer chaque mois, par exemple) :

```
python peb_resolveurs.py --test
```

## Lire les résultats

### Niveaux de confiance

| Confiance | Signification |
| --- | --- |
| haute | État de collection fermé qui couvre l'année, ou résolveur de liens de la BU (à jour) |
| moyenne | État de collection ouvert (« 2001-.... ») : la BU reçoit peut-être encore la revue, à confirmer |
| faible | Douteux : titre passé en version uniquement électronique, ancien titre, année du changement de titre |

### Codes PEB (zone 930 $j du Sudoc)

| Code | Signification |
| --- | --- |
| u | Disponible pour le PEB |
| f | Reproduction seulement |
| s | PEB soumis à condition |
| g | Non disponible pour le PEB |
| v | Disponible sous forme électronique (libellé à confirmer) |

Sans code, le Sudoc considère l'exemplaire comme disponible pour le PEB.

## Couverture des BU prioritaires

Sur les 18 RCR de la liste, 8 BU sont interrogées automatiquement : 7 par 6 résolveurs Alma publics (Montpellier sert à la fois l'odontologie et Nîmes), et Nantes par l'export HLM de Nantilus.

| BU | Établissement | Code Alma | Statut |
| --- | --- | --- | --- |
| BU Santé (Vandœuvre-lès-Nancy) | Université de Lorraine | `33UDL_INST` | interrogée |
| BU Santé (Dijon) | Université de Bourgogne | `33UB_INST` | interrogée |
| BU Médecine Pharmacie (Besançon) | Université de Franche-Comté | `33UFC_INST` | interrogée |
| Odontologie (Montpellier) | Université de Montpellier | `33MON_INST` | interrogée |
| BU Médecine (Nîmes) | Université de Montpellier | `33MON_INST` | interrogée |
| BU Sciences du Vivant et de la Santé | Université de Bordeaux | `33PUDB_UB` | interrogée |
| BU Santé - Learning Center (Loos) | Université de Lille | `33UDLILLE_INST` | interrogée |
| BU Odontologie, Lyon Sud, Rockefeller | Université Lyon 1 | — | EBSCO, authentification requise |
| BU Santé (Limoges) | Université de Limoges | — | EBSCO, authentification requise |
| BU Santé (Rennes) | Université de Rennes | — | EBSCO, authentification requise |
| BU Santé UBO (Brest) | Université de Bretagne Occidentale | — | EBSCO, authentification requise |
| Pôle Pharmacie-Biologie-Cosmétologie (Paris) | Université Paris Cité | non trouvé | Alma, code à identifier |
| BU Santé (Nantes) | Nantes Université | — | export HLM Nantilus (`peb_nantes.py`) |
| BU Tampon | Université de La Réunion | — | Résolveur à identifier |
| Bibliothèque du Pôle Santé (Reims) | Université de Reims Champagne-Ardenne | — | Résolveur à identifier |
| BU Santé (Saint-Priest-en-Jarez) | Université Jean Monnet Saint-Étienne | — | Résolveur à identifier |
| BU Madeleine Brès (Caen) | Université de Caen Normandie | — | Résolveur à identifier |

La BU Odontologie, d'une part, et Lyon Sud et Rockefeller, d'autre part, ont deux RCR distincts à Lyon 1.

Les BU non interrogées automatiquement restent couvertes par le Sudoc.

## Limites connues

- **Clauses PEB des licences électroniques :** elles ne sont pas publiées par les résolveurs. La colonne PEB indique « clause PEB à vérifier ».
- **Libre accès « signalé » :** les lignes signalées par Mir@bel, ou marquées comme contenu offert dans un bouquet payant, ne couvrent souvent qu'une partie des articles. Elles n'arrêtent pas la demande.
- **Repérage des hôpitaux :** il se fait d'après le nom court de la bibliothèque et devra être affiné.
- **Dates de publication :** beaucoup de notices de périodiques n'ont pas de zone 100. Les dates des titres liés sont alors estimées à partir de leurs successeurs ou prédécesseurs.
- **Export Nantilus :** il n'est pas mis à jour automatiquement. Un abonnement arrêté après l'export apparaît encore « en cours ». La base de connaissances décrit ce que Nantes déclare, pas les droits réels ; les écarts se vérifient sur le jeu de test.
- **OpenAlex sans clé :** sans clé d'API, le budget quotidien est partagé entre tous les utilisateurs du réseau. Une clé gratuite sera utile en production.
