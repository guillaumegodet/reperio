#!/usr/bin/env python3
"""
peb_nantes.py — Étape 0 : la revue est-elle déjà accessible à Nantes Université ?

Source : l'export brut EBSCO Holdings Management (HLM) du catalogue Nantilus, le même que
celui qu'utilise l'onglet « Revues » de Druid. Il décrit, titre par titre et bouquet par
bouquet, la couverture électronique de Nantes Université : abonnements, archives,
Licences nationales activées, bouquets en libre accès.

L'export pèse environ 300 Mo. On en tire une fois un petit index (revues seulement), gardé
hors du dépôt (dossier donnees/, ignoré par git) :

    python peb_nantes.py --indexer chemin/vers/export_hlm.csv [--date-export 2026-07-01]

Puis, seul ou depuis reperio.py :

    python peb_nantes.py --issn 0002-9343 --annee 1998
    python peb_nantes.py --etat            # date de l'export, nombre de titres indexés

Règles reprises de Druid (druid-biblio, scripts/enrich_journals_nantilus.py) :
    - la couverture propre à NU (CustomCoverage*) passe avant celle d'EBSCO (ManagedCoverage*) ;
    - les lignes masquées (HideOnPublicationFinder) ou supprimées (Delete) sont ignorées.
Ajouts propres au PEB : contrôle de l'année demandée sur chaque plage de couverture (et non
sur une plage min–max), prise en compte de l'embargo, nature de l'accès par bouquet.
"""
import argparse, csv, datetime, gzip, json, os, re, sys
from itertools import zip_longest

ICI = os.path.dirname(os.path.abspath(__file__))
INDEX = os.environ.get("REPERIO_INDEX_NANTES", os.path.join(ICI, "donnees", "fonds_nantes.json.gz"))
# Lien public (recherche par ISSN dans Nantilus) : les URL de l'export passent par le proxy et le CAS
CATALOGUE = "https://nantilus.univ-nantes.fr/vufind/Search/Results?lookfor={issn}&type=ISN"
RCR = "441092101"                 # BU Santé de Nantes, ligne de resolveurs.csv servie par cet index
ETABLISSEMENT = "Nantes Université"
EXPORT_ANCIEN = 120               # jours : au-delà, le rapport signale un export à rafraîchir
TYPES_EXCLUS = {"Book", "Database", "Web site", "Streaming Video", "Streaming Audio"}

csv.field_size_limit(10 ** 8)


# --------------------------------------------------------------------------- indexation

def _issn(v):
    s = (v or "").strip().upper().replace("-", "")
    return s if re.fullmatch(r"\d{7}[\dX]", s) else ""


def nature(paquet, udf4, contenu):
    """Nature de l'accès d'après le nom du bouquet et le champ local UserDefinedField4."""
    if udf4 == "LN" or re.search(r"licences?\s+nationales?|ISTEX", paquet, re.I):
        return "licence nationale"
    if udf4 == "Libre accès" or re.search(
            r"open access|\bopen\b|DOAJ|PubMed Central|\bPMC\b|Gallica|gratuit|\blibre\b|\bfree\b", paquet, re.I):
        return "libre accès"
    if udf4 == "Archives pérennes":
        return "archives pérennes"
    if contenu == "AggregatedFullText":     # « Mixed Content » = aussi des titres souscrits un à un
        return "agrégateur"
    return "abonnement"


def indexer(chemin_hlm, date_export=None, sortie=INDEX):
    if not date_export:
        date_export = datetime.date.fromtimestamp(os.path.getmtime(chemin_hlm)).isoformat()
    lignes, par_issn, n = [], {}, 0
    with open(chemin_hlm, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            n += 1
            if r.get("ResourceType", "") in TYPES_EXCLUS:
                continue
            if r.get("HideOnPublicationFinder", "").strip().upper() == "Y" \
                    or r.get("Delete", "").strip().upper() == "Y":
                continue
            issns = {i for i in (_issn(r.get("PrintISSN")), _issn(r.get("OnlineISSN"))) if i}
            if not issns:
                continue
            if r.get("CustomCoverageBegin") or r.get("CustomCoverageEnd"):
                debut, fin, perso = r["CustomCoverageBegin"], r["CustomCoverageEnd"], True
            else:
                debut, fin, perso = r.get("ManagedCoverageBegin", ""), r.get("ManagedCoverageEnd", ""), False
            paquet = (r.get("PackageName") or "").strip()
            contenu = r.get("PackageContentType", "")
            lignes.append({
                "titre": (r.get("Title") or "").strip(),
                "paquet": paquet,
                "debut": debut, "fin": fin, "perso": perso,
                "embargo": (r.get("CustomEmbargo") or r.get("Embargo") or "").strip(),
                "nature": nature(paquet, (r.get("UserDefinedField4") or "").strip(), contenu),
                "agrege": contenu == "AggregatedFullText",
                "url": (r.get("URL") or "").strip(),       # adresse directe, sans le proxy
            })
            for i in issns:
                par_issn.setdefault(i, []).append(len(lignes) - 1)
            if n % 100000 == 0:
                print(f"  … {n:,} lignes lues, {len(lignes):,} gardées", flush=True)
    os.makedirs(os.path.dirname(sortie), exist_ok=True)
    meta = {"source": os.path.basename(chemin_hlm), "date_export": date_export,
            "indexe_le": datetime.date.today().isoformat(), "lignes_export": n,
            "lignes": len(lignes), "issn": len(par_issn)}
    with gzip.open(sortie, "wt", encoding="utf-8") as f:
        json.dump({"meta": meta, "lignes": lignes, "issn": par_issn}, f, ensure_ascii=False,
                  separators=(",", ":"))
    _CHARGE.clear()
    return meta


# --------------------------------------------------------------------------- lecture

_CHARGE = {}


def charger(chemin=INDEX):
    """Index en mémoire, ou None s'il n'a pas été construit."""
    if chemin not in _CHARGE:
        try:
            with gzip.open(chemin, "rt", encoding="utf-8") as f:
                _CHARGE[chemin] = json.load(f)
        except FileNotFoundError:
            _CHARGE[chemin] = None
    return _CHARGE[chemin]


def etat():
    """(disponible, libellé court) — pour le rapport et peb_resolveurs."""
    idx = charger()
    if not idx:
        return False, "index Nantilus absent (python peb_nantes.py --indexer …)"
    m = idx["meta"]
    age = (datetime.date.today() - datetime.date.fromisoformat(m["date_export"])).days
    txt = f"export Nantilus du {_fr(m['date_export'])}"
    if age > EXPORT_ANCIEN:
        txt += f" ({age} jours : à rafraîchir)"
    return True, txt


def _fr(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if len(iso) >= 10 else iso


def _date(s):
    try:
        return datetime.date.fromisoformat(s.strip()[:10])
    except ValueError:
        m = re.match(r"(\d{4})", s.strip())
        return datetime.date(int(m.group(1)), 1, 1) if m else None


def _moins_embargo(jour, embargo):
    """'4 years', '6 months', '14 days' -> dernière date accessible."""
    m = re.match(r"(\d+)\s*(day|week|month|year)", embargo or "", re.I)
    if not m:
        return jour
    n, u = int(m.group(1)), m.group(2).lower()
    if u == "day":
        return jour - datetime.timedelta(days=n)
    if u == "week":
        return jour - datetime.timedelta(weeks=n)
    mois = n * (12 if u == "year" else 1)
    a, mo = divmod(jour.year * 12 + jour.month - 1 - mois, 12)
    return datetime.date(a, mo + 1, 1)


def _plages(ligne):
    """Plages (début, fin) d'une ligne ; fin None = en cours. Plusieurs plages séparées par « | »."""
    for d, f in zip_longest(ligne["debut"].split("|"), ligne["fin"].split("|"), fillvalue=""):
        f = f.strip()
        yield _date(d) if d.strip() else None, None if f.lower() in ("", "present") else _date(f)


def couverture(ligne, annee, aujourdhui=None):
    """Renvoie (couvre, partielle, texte de la plage concernée)."""
    aujourdhui = aujourdhui or datetime.date.today()
    textes, trouve = [], None
    for debut, fin in _plages(ligne):
        dernier = fin or _moins_embargo(aujourdhui, ligne["embargo"])
        txt = f"{debut:%Y-%m}" if debut else "?"
        txt += f" → {fin:%Y-%m}" if fin else " → aujourd'hui"
        textes.append(txt)
        if trouve:
            continue
        if (debut and annee < debut.year) or annee > dernier.year:
            continue
        partielle = (debut is None or (annee == debut.year and debut.month > 1)
                     or (annee == dernier.year and dernier.month < 12))
        trouve = (True, partielle, txt)
    emb = f" (embargo {ligne['embargo']})" if ligne["embargo"] else ""
    if trouve:
        return trouve[0], trouve[1], trouve[2] + emb
    return False, False, " | ".join(textes) + emb


STATUTS = {
    "abonnement": "accès NU (abonnement)",
    "archives pérennes": "accès NU (archives pérennes)",
    "licence nationale": "accès NU (Licence nationale)",
    "libre accès": "accès NU (libre accès)",
    "agrégateur": "accès NU (agrégateur)",
}


def evaluer(libelle, issns, annee):
    """Renvoie (verdict, lignes) au format commun de reperio ; verdict non vide = déjà à Nantes."""
    idx = charger()
    if not idx:
        return "", []
    _, source = etat()
    vus, couvrantes, hors = set(), [], []
    for issn in issns:
        for i in idx["issn"].get(_issn(issn), []):
            if i in vus:
                continue
            vus.add(i)
            l = dict(idx["lignes"][i], issn=issn)
            couvre, partielle, txt = couverture(l, int(annee))
            (couvrantes if couvre else hors).append((l, partielle, txt))

    lignes, verdicts = [], []

    def ligne(statut, confiance, l, txt, detail):
        lignes.append({"demande": libelle, "annee": annee, "statut": statut, "confiance": confiance,
                       "bibliotheque": f"{ETABLISSEMENT} — {l['paquet']}", "type": "accès en ligne",
                       "rcr": RCR, "prioritaire": "Nantes", "support": "électronique",
                       "couverture": txt, "peb": "sans objet (accès direct NU)",
                       "source": source, "detail": detail,
                       "url": CATALOGUE.replace("{issn}", l["issn"].strip())})

    for l, partielle, txt in couvrantes:
        douteux = partielle or l["agrege"]
        raisons = [r for r, ok in (("année couverte en partie", partielle),
                                   ("agrégateur : articles parfois manquants", l["agrege"]),
                                   ("couverture saisie par NU", l["perso"])) if ok]
        detail = l["titre"] + (" — " + ", ".join(raisons) if raisons else "")
        ligne(STATUTS[l["nature"]], "moyenne" if douteux else "haute", l, txt, detail)
        if not douteux:
            verdicts.append(f"{l['paquet']} ({l['nature']})")
    if not couvrantes:
        for l, _, txt in hors:
            ligne("à NU, hors de l'année demandée", "faible", l, txt, f"{l['titre']} — {l['nature']}")

    lignes.sort(key=lambda x: {"haute": 0, "moyenne": 1}.get(x["confiance"], 2))
    verdict = ("accessible à Nantes Université : " + " ; ".join(dict.fromkeys(verdicts))) if verdicts else ""
    return verdict, lignes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--indexer", metavar="EXPORT_HLM", help="construire l'index depuis l'export HLM (CSV)")
    ap.add_argument("--date-export", help="date de l'export (AAAA-MM-JJ), par défaut celle du fichier")
    ap.add_argument("--etat", action="store_true", help="afficher l'état de l'index")
    ap.add_argument("--issn", nargs="+")
    ap.add_argument("--annee", type=int)
    a = ap.parse_args()
    if a.indexer:
        m = indexer(a.indexer, a.date_export)
        print(f"Index écrit : {INDEX}\n  export du {_fr(m['date_export'])}, {m['lignes_export']:,} lignes lues, "
              f"{m['lignes']:,} lignes de revues gardées, {m['issn']:,} ISSN")
        return
    if a.etat:
        ok, txt = etat()
        print(txt)
        if ok:
            m = charger()["meta"]
            print(f"  {m['lignes']:,} lignes, {m['issn']:,} ISSN, indexé le {_fr(m['indexe_le'])}")
        sys.exit(0 if ok else 1)
    if not (a.issn and a.annee):
        ap.error("donner --indexer, --etat, ou --issn et --annee")
    if not charger():
        sys.exit(etat()[1])
    verdict, lignes = evaluer(" / ".join(a.issn), a.issn, a.annee)
    print("Verdict :", verdict or "pas d'accès électronique à Nantes pour cette année")
    for l in lignes:
        print(f"  {l['confiance']:<8} {l['statut']:<30} {l['bibliotheque'][19:70]:<52} {l['couverture']}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
