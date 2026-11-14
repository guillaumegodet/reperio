# Projet PEB-Loc : localiser automatiquement les revues dans les BU françaises

Nov 14, 2026 · @Guillaume

## Contexte et objectif

Objectif : pour une revue et une année données, obtenir en quelques secondes la liste des bibliothèques françaises qui la possèdent, en papier ou en électronique, avec un niveau de confiance.

Aujourd'hui, les collègues du PEB visitent un à un les catalogues des BU. Chaque BU a son propre parcours (catalogue, outil de découverte, renvoi vers EBSCO, etc.). Le Sudoc est fiable pour le papier, mais les états de collection électroniques y sont rarement à jour.

Un prototype de l'étape papier existe déjà (`peb_sudoc.py`). Testé sur trois demandes réelles (La Presse médicale 2023, American Journal of Medicine 2024, Caries research 2016), il a trouvé 4 à 10 localisations papier par demande.

## Périmètre

L'outil localise et classe ; la décision et la demande de PEB restent humaines.

| Dans le périmètre | Hors périmètre |
| --- | --- |
| Revues (ISSN), une ou plusieurs années par demande | Monographies, chapitres |
| Papier : états de collection du Sudoc | Envoi automatique des demandes de PEB |
| Électronique : libre accès, Licences nationales, abonnements des BU | Vérification des droits d'accès individuels |
| BU françaises de l'ESR, centres hospitaliers en option | Bibliothèques étrangères (WorldCat, Subito) dans un premier temps |
| Indication des clauses PEB des licences quand elles sont connues | Négociation ou suivi des licences |

## Architecture

Trois niveaux de sources, du plus sûr au plus coûteux à maintenir ; chaque résultat garde la trace de sa source.

&#91;embedded content: chaîne de traitement · 3 niveaux de sources\]

Le Sudoc fait foi pour le papier ; pour l'électronique, les résolveurs de liens des BU sont la source à jour, BACON ne donnant qu'une présomption. Stockage et configuration : Grist (table des résolveurs, cache, historique des demandes).

## Phases et livrables

Cinq phases, chacune utilisable seule : le PEB gagne du temps dès la phase 1.

1. **Phase 0 — Cadrage avec le PEB.** Recueillir 30 à 50 demandes réelles récentes avec la réponse trouvée à la main : ce sera le jeu de test. Lister les BU les plus sollicitées et le format de sortie attendu.
   - Critère de fin : jeu de test validé, liste des 20 BU prioritaires.
2. **Phase 1 — Papier via le Sudoc.** Industrialiser `peb_sudoc.py` : suivi automatique des ISSN papier/électronique et des changements de titre, filtre BU / centres hospitaliers, décodage des codes PEB (zone 930 $j), cache des réponses.
   - Critère de fin : sur le jeu de test, au moins 90 % des localisations papier trouvées à la main sont aussi trouvées par l'outil.
3. **Phase 2 — Accès libre et national.** Vérifier d'abord si l'année est en libre accès (Unpaywall/OpenAlex, DOAJ, Mir@bel) ou couverte par les Licences nationales / ISTEX (BACON). Si oui, la demande s'arrête là.
   - Critère de fin : part des demandes résolues sans PEB mesurée sur le jeu de test.
4. **Phase 3 — Résolveurs de liens des BU prioritaires.** Constituer la table de configuration (BU → type de résolveur → URL → code institution), puis interroger chaque résolveur par OpenURL (ISSN + année). Commencer par les 20 BU prioritaires.
   - Critère de fin : 20 BU interrogées automatiquement, résultats comparés à une vérification manuelle.
5. **Phase 4 — Outil pour l'équipe.** Une interface simple (Grist ou page web) : on saisit le titre ou l'ISSN et l'année, on obtient un tableau trié BU | support | couverture | source | confiance | clause PEB.
   - Critère de fin : l'équipe PEB l'utilise en routine pendant un mois.

## Calendrier indicatif

Environ neuf mois à temps partiel, avec un premier outil utilisable par le PEB dès le troisième mois.

&#91;embedded content: feuille de route indicative · 5 phases, en mois\]

Durées à ajuster selon le temps disponible ; la phase 2 peut se mener en parallèle de la phase 1.

## Organisation et rôles

Un porteur au service bibliométrie, l'équipe PEB comme référente métier.

| Rôle | Qui | Contribution |
| --- | --- | --- |
| Pilotage et développement | Service bibliométrie | Scripts, table de configuration, interface |
| Référent métier | Équipe PEB | Jeu de test, validation des résultats, retours d'usage |
| Ressources électroniques | Service de la documentation électronique | Clauses PEB des licences, contacts résolveurs |
| Partenaires externes | ABES, Couperin, BU partenaires | Questions sur Periscope/BACON, échanges sur les résolveurs |

Noms à confirmer pour chaque rôle.

## Risques et points de vigilance

Le risque principal est de donner une réponse fausse avec assurance : chaque résultat affiche donc sa source et son niveau de confiance.

| Risque | Effet | Parade |
| --- | --- | --- |
| États de collection ouverts (« 2001-.... ») jamais fermés | BU signalée à tort | Statut « à confirmer », priorité aux états fermés |
| Électronique absent ou périmé dans le Sudoc | BU manquées | Interroger les résolveurs de liens (phase 3) |
| Résolveurs inaccessibles hors du réseau de l'établissement | Phase 3 partielle | Tester tôt, demander un accès aux BU partenaires |
| Accès électronique sans droit de PEB | Demande refusée | Colonne « clause PEB », à renseigner avec la documentation électronique |
| Changements de titre et d'ISSN | Années manquées | Suivre les notices liées dans le Sudoc (phase 1) |
| Charge sur les serveurs ABES et des BU | Blocage | Pause entre requêtes, cache, usage raisonnable |
| Maintenance de la table des résolveurs | Outil qui se dégrade | Test automatique mensuel, signalement des échecs |

## Indicateurs de réussite

Le projet réussit s'il divise par au moins deux le temps de localisation, sans perte de fiabilité. Les valeurs de départ sont à mesurer en phase 0.

| Indicateur | Mesure |
| --- | --- |
| Temps moyen de localisation par demande | Avant / après, sur le jeu de test |
| Rappel papier | Part des localisations manuelles retrouvées par l'outil (cible : 90 %) |
| Fiabilité | Part des BU proposées qui ont réellement le numéro |
| Demandes évitées | Part des demandes résolues par le libre accès ou les Licences nationales |
| Adoption | Part des demandes traitées avec l'outil après un mois |

## Prochaines étapes immédiates

- [ ] Lancer `peb_sudoc.py` sur le réseau de Nantes Université avec les trois demandes d'exemple
- [ ] Présenter le prototype à l'équipe PEB et recueillir 30 à 50 demandes récentes avec leur réponse
- [ ] Faire décoder les codes PEB de la zone 930 $j (documentation ABES ou équipe PEB)
- [ ] Tester l'interrogation de 3 résolveurs de liens (un Alma, un SFX, un EBSCO) depuis l'extérieur
- [ ] Demander à la documentation électronique la liste des clauses PEB des principales licences
