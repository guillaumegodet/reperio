#!/usr/bin/env python3
"""
peb_resolveurs.py — Phase 3 : interroger les résolveurs de liens des BU prioritaires.

La table resolveurs.csv décrit chaque BU : type de résolveur, hôte, code institution.
Seuls les résolveurs Alma publics (statut « actif ») sont interrogés pour l'instant.
Le type « hlm » (Nantes) n'est pas un résolveur : il renvoie à l'index local de peb_nantes.py.

Usage :
    python peb_resolveurs.py --issn 0002-9343 1555-7162 --annee 2020
    python peb_resolveurs.py --test          # vérifie que chaque résolveur actif répond

Requête Alma (OpenURL, réponse XML) :
    https://{hote}.alma.exlibrisgroup.com/view/uresolver/{institution}/openurl?rft.issn=...&rft.year=...&svc_dat=CTO
"""
import argparse, csv, datetime, os, re, sys, urllib.parse
import xml.etree.ElementTree as ET
from peb_sudoc import get
import peb_nantes

ICI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ICI, "resolveurs.csv")
NS = {"u": "http://com/exlibris/urm/uresolver/xmlbeans/u"}
TEST_ISSN, TEST_ANNEE = "0002-9343", 2020      # American Journal of Medicine, très largement souscrit


def charger_config(chemin=CONFIG):
    with open(chemin, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _nettoyer(s):
    return re.sub(r"<[^>]+>", " ", s or "").replace("&lt;br>", " ").strip()


def couvre(availability, annee):
    """Lit « Available from 01/01/1967 until 2020. Most recent 1 year(s) not available. »"""
    m = re.search(r"from\s+(?:\S*?/)?(\d{4})", availability)
    if not m or annee < int(m.group(1)):
        return False
    m = re.search(r"until\s+(?:\S*?/)?(\d{4})", availability)
    if m and annee > int(m.group(1)):
        return False
    m = re.search(r"[Mm]ost recent (\d+) year", availability)
    if m and annee > datetime.date.today().year - int(m.group(1)):
        return False
    return True


def alma(conf, issn, annee):
    """Renvoie la liste des services texte intégral pour (issn, annee), ou None si pas de réponse."""
    params = {"ctx_ver": "Z39.88-2004", "ctx_enc": "info:ofi/enc:UTF-8", "url_ver": "Z39.88-2004",
              "rft.genre": "journal", "rft.issn": issn, "rft.year": annee, "rft.date": annee,
              "svc_dat": "CTO"}
    url = (f"https://{conf['hote']}.alma.exlibrisgroup.com/view/uresolver/{conf['institution']}/openurl?"
           + urllib.parse.urlencode(params))
    try:
        txt = get(url)
    except RuntimeError:
        return None
    if not txt:
        return None
    root = ET.fromstring(txt)
    services = []
    for cs in root.iterfind(".//u:context_service", NS):
        if cs.get("service_type") != "getFullTxt":
            continue
        k = {e.get("id"): (e.text or "") for e in cs.iterfind("u:keys/u:key", NS)}
        dispo = _nettoyer(k.get("Availability"))
        filtre = k.get("Filtered") == "true"
        raison = k.get("Filter reason", "")
        if not filtre:
            ok = True
        elif "date" in raison.lower():
            ok = False
        else:
            # Filtre d'accès (ex. groupe d'adresses IP) : la ressource existe dans l'établissement,
            # on juge la couverture d'après le texte « Available from ... »
            ok = couvre(dispo, int(annee))
        services.append({
            "paquet": k.get("package_public_name") or k.get("package_name", ""),
            "couverture": dispo,
            "couvre_annee": ok,
            "raison_filtre": k.get("Filter reason", ""),
            "libre": k.get("Is_free") == "1",
            "licence": k.get("license_exist") == "true",
            "note": _nettoyer(k.get("Authentication_note")),
            "url": (cs.findtext("u:resolution_url", default="", namespaces=NS) or "").strip(),
        })
    return services


def interroger(libelle, issns, annee, config=None):
    """Lignes au format commun pour toutes les BU actives de la configuration."""
    config = config or charger_config()
    lignes, etat = [], {}
    deja = set()       # un même résolveur (ex. Montpellier) peut servir plusieurs BU
    for conf in config:
        if conf["type"] == "hlm":      # lignes produites par peb_nantes.evaluer, appelé par reperio.py
            ok, txt = peb_nantes.etat()
            etat[conf["rcr"]] = "interrogé" if ok else txt
            continue
        if conf["type"] != "alma" or conf["statut"] != "actif":
            etat[conf["rcr"]] = conf["statut"]
            continue
        cle_res = (conf["hote"], conf["institution"])
        services, repondu = [], False
        for issn in issns:
            r = alma(conf, issn, annee)
            if r is not None:
                repondu = True
                services += r
        etat[conf["rcr"]] = "interrogé" if repondu else "pas de réponse"
        # Une ligne par BU : les bouquets qui couvrent l'année sont regroupés
        couvrants = {}
        motif = (conf.get("filtre_paquet") or "").strip()
        for s in services:
            if motif and not re.search(motif, s["paquet"], re.I):
                continue
            if s["couvre_annee"]:
                couvrants.setdefault(s["paquet"], s)
        if couvrants:
            ss = list(couvrants.values())
            lignes.append({
                "demande": libelle, "annee": annee,
                "statut": "libre accès" if all(s["libre"] for s in ss) else "oui (accès en ligne)",
                "confiance": "haute",
                "bibliotheque": f"{conf['etablissement']} ({conf['bibliotheque']})",
                "type": "BU", "rcr": conf["rcr"], "prioritaire": "oui",
                "support": "électronique",
                "couverture": " | ".join(dict.fromkeys(s["couverture"] for s in ss)),
                "peb": "clause PEB à vérifier" + (" (licence enregistrée)" if any(s["licence"] for s in ss) else ""),
                "source": f"résolveur Alma {conf['institution']}",
                "detail": " ; ".join(couvrants) + (" — même résolveur qu'une autre BU" if cle_res in deja else ""),
                "url": ss[0]["url"],
            })
        deja.add(cle_res)
    return lignes, etat


def tester():
    ok = True
    for conf in charger_config():
        if conf["type"] == "hlm":
            _, txt = peb_nantes.etat()      # index local : son absence (ex. en CI) n'est pas un échec
            print(f"  {conf['rcr']} {conf['etablissement']:<40} {'index local':<16} {txt}")
            continue
        if conf["type"] != "alma" or conf["statut"] != "actif":
            print(f"  {conf['rcr']} {conf['etablissement']:<40} {conf['statut']}")
            continue
        r = alma(conf, TEST_ISSN, TEST_ANNEE)
        msg = "OK" if r else ("répond mais aucun service" if r == [] else "ÉCHEC")
        ok &= bool(r)
        print(f"  {conf['rcr']} {conf['etablissement']:<40} {conf['institution']:<16} {msg}")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issn", nargs="+")
    ap.add_argument("--annee", type=int)
    ap.add_argument("--test", action="store_true", help="vérifier que les résolveurs actifs répondent")
    a = ap.parse_args()
    if a.test:
        import peb_sudoc
        peb_sudoc.UTILISER_CACHE = False
        sys.exit(0 if tester() else 1)
    if not (a.issn and a.annee):
        ap.error("donner --issn et --annee, ou --test")
    lignes, etat = interroger(" / ".join(a.issn), a.issn, a.annee)
    for l in lignes:
        print(f"  {l['bibliotheque'][:45]:<46} {l['couverture'][:60]:<61} {l['detail'][:40]}")
    print("\nÉtat des BU :", ", ".join(f"{k}={v}" for k, v in etat.items()))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
