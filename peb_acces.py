#!/usr/bin/env python3
"""
peb_acces.py — Phase 2 : l'année demandée est-elle accessible sans PEB ?

    - libre accès : OpenAlex (part des articles de l'année en accès ouvert, revue au DOAJ)
    - Licences nationales et bouquets libres : BACON (ABES), ISTEX

Usage seul :
    python peb_acces.py --issn 0002-9343 --annee 1998

Sources (publiques, sans clé) :
    https://api.openalex.org/sources/issn:{issn}
    https://api.openalex.org/works?filter=...&group_by=open_access.is_oa
    https://bacon.abes.fr/id2kbart/{issn}.json
    https://api.istex.fr/document/?q=...
"""
import argparse, datetime, json, re, sys, urllib.parse
from peb_sudoc import get, as_list

SEUIL_OA_COMPLET = 0.95   # au-delà : on considère l'année entièrement en accès ouvert
SEUIL_OA_PARTIEL = 0.20


def _txt(v):
    """BACON renvoie {} pour les champs vides."""
    return v.strip() if isinstance(v, str) else ""


def openalex(issns, annee):
    """Renvoie (infos revue, nb articles de l'année, nb en accès ouvert)."""
    revue = {}
    for issn in issns:
        try:
            txt = get(f"https://api.openalex.org/sources/issn:{issn}?select=display_name,is_oa,is_in_doaj,homepage_url")
        except RuntimeError:
            txt = None
        if txt:
            revue = json.loads(txt)
            break
    filtre = f"primary_location.source.issn:{'|'.join(issns)},publication_year:{annee}"
    total = oa = 0
    try:
        txt = get("https://api.openalex.org/works?" + urllib.parse.urlencode(
            {"filter": filtre, "group_by": "open_access.is_oa"}))
    except RuntimeError:
        txt = None
    if txt:
        for g in json.loads(txt).get("group_by", []):
            total += g["count"]
            if g["key"] == "true":
                oa += g["count"]
    return revue, total, oa


def _embargo_annee(embargo):
    """'P12M' (les 12 derniers mois ne sont pas accessibles) -> dernière année accessible."""
    m = re.fullmatch(r"P(\d+)([YM])", embargo or "")
    if not m:
        return None
    mois = int(m.group(1)) * (12 if m.group(2) == "Y" else 1)
    d = datetime.date.today()
    return (d.year * 12 + d.month - 1 - mois) // 12


def bacon(issns, annee):
    """Lignes KBART de BACON couvrant l'année. Renvoie [(paquet, couverture, nature, accès)]."""
    res, vus = [], set()
    for issn in issns:
        try:
            txt = get(f"https://bacon.abes.fr/id2kbart/{issn}.json")
        except RuntimeError:
            continue
        if not txt:
            continue
        try:
            fournisseurs = as_list(json.loads(txt)["query"].get("provider"))
        except (ValueError, KeyError, AttributeError):
            continue
        for p in fournisseurs:
            for k in as_list(p.get("kbart")):
                debut = _txt(k.get("date_first_issue_online"))[:4]
                fin = _txt(k.get("date_last_issue_online"))[:4]
                emb = _embargo_annee(_txt(k.get("embargo_info")))
                if not debut.isdigit() or annee < int(debut):
                    continue
                if fin.isdigit() and annee > int(fin):
                    continue
                if emb is not None and annee > emb:
                    continue
                cle = (p["package"], debut, fin)
                if cle in vus:
                    continue
                vus.add(cle)
                paquet = p["package"]
                if _txt(k.get("coverage_depth")) not in ("", "fulltext"):
                    continue          # sommaires, résumés : pas d'accès au texte
                if re.search(r"(^|[_-])LN([_-]|$)", paquet.upper()):
                    nature = "Licence nationale"
                elif _txt(k.get("access_type")) == "F" and re.search(
                        r"OPEN|(^|_)OA([_-]|$)|DOAJ|FREE|LIBRE|GRATUIT", paquet.upper()) \
                        and not paquet.upper().startswith("MIRABEL"):
                    nature = "accès libre"
                elif _txt(k.get("access_type")) == "F":
                    # Mir@bel, ou contenu offert dans un bouquet payant (« complimentary content ») :
                    # souvent une partie des articles seulement
                    nature = "accès libre signalé"
                else:
                    nature = "bouquet payant"
                couverture = f"{debut}-{fin or '....'}" + (f" (embargo {_txt(k.get('embargo_info'))})" if emb else "")
                res.append((paquet, couverture, nature, _txt(k.get("title_url"))))
    return res


def istex(issns, annee):
    q = " OR ".join(f'host.issn:"{i}" OR host.eissn:"{i}"' for i in issns)
    try:
        txt = get("https://api.istex.fr/document/?" + urllib.parse.urlencode(
            {"q": f"({q}) AND publicationDate:{annee}", "size": 0}))
    except RuntimeError:
        return None
    return json.loads(txt).get("total", 0) if txt else 0


def evaluer(libelle, issns, annee):
    """Renvoie (verdict, lignes) ; verdict non vide = la demande peut s'arrêter là."""
    lignes, verdicts = [], []

    def ligne(statut, confiance, bib, couverture, source, url="", detail=""):
        lignes.append({"demande": libelle, "annee": annee, "statut": statut, "confiance": confiance,
                       "bibliotheque": bib, "type": "accès en ligne", "rcr": "", "prioritaire": "",
                       "support": "électronique", "couverture": couverture, "peb": "sans objet",
                       "source": source, "detail": detail, "url": url})

    revue, total, oa = openalex(issns, annee)
    part = oa / total if total else 0
    if revue.get("is_in_doaj"):
        verdicts.append("revue en libre accès (DOAJ)")
        ligne("libre accès", "haute", "Revue en accès ouvert (DOAJ)", str(annee), "OpenAlex / DOAJ",
              revue.get("homepage_url") or "")
    elif total and part >= SEUIL_OA_COMPLET:
        verdicts.append(f"{oa}/{total} articles en accès ouvert")
        ligne("libre accès", "haute", "Articles en accès ouvert", f"{oa}/{total} articles", "OpenAlex")
    elif total and part >= SEUIL_OA_PARTIEL:
        ligne("libre accès partiel", "moyenne", "Articles en accès ouvert",
              f"{oa}/{total} articles ({part:.0%})", "OpenAlex",
              detail="vérifier l'article demandé (DOI) dans Unpaywall / OpenAlex")

    for paquet, couv, nature, url in bacon(issns, annee):
        if nature == "Licence nationale":
            verdicts.append(f"Licence nationale ({couv}, BACON)")
            ligne("Licence nationale", "haute", "Licence nationale (établissements ayants droit)",
                  couv, "BACON", url, paquet)
        elif nature == "accès libre":
            verdicts.append(f"bouquet en accès libre ({paquet})")
            ligne("libre accès", "haute", "Bouquet en accès libre", couv, "BACON", url, paquet)
        elif nature == "accès libre signalé":
            ligne("libre accès à vérifier", "moyenne", "Accès libre signalé (partiel ?)", couv,
                  "BACON", url, f"{paquet} — peut ne concerner qu'une partie des articles")
        else:
            ligne("présent dans un bouquet", "faible", "Bouquet payant (BU abonnées : voir résolveurs)",
                  couv, "BACON", url, paquet)

    n_istex = istex(issns, annee)
    if n_istex:
        verdicts.append(f"ISTEX : {n_istex} documents de {annee}")
        ligne("ISTEX", "haute", "ISTEX (établissements ayants droit)", f"{n_istex} documents",
              "ISTEX", f"https://search.istex.fr/?q=host.issn:%22{issns[0]}%22", "")

    return " ; ".join(dict.fromkeys(verdicts)), lignes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issn", nargs="+", required=True)
    ap.add_argument("--annee", type=int, required=True)
    a = ap.parse_args()
    verdict, lignes = evaluer(" / ".join(a.issn), a.issn, a.annee)
    print("Verdict :", verdict or "pas d'accès libre ou national trouvé -> PEB")
    for l in lignes:
        print(f"  {l['statut']:<24} {l['bibliotheque'][:45]:<46} {l['couverture']:<22} {l['source']} {l['detail'][:50]}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
