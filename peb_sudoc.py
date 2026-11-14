#!/usr/bin/env python3
"""
peb_sudoc.py — Localiser une année de revue dans les bibliothèques du Sudoc
(phase 1 : états de collection papier et électronique déclarés dans le Sudoc).

Usage :
    python peb_sudoc.py demandes.csv            -> écrit resultats_peb.csv
    python peb_sudoc.py --issn 0008-6568 --annee 2016
    python peb_sudoc.py demandes.csv --sans-hopitaux --sans-cache

demandes.csv (séparateur ;) : libelle;issn;annee
    Un seul ISSN suffit : l'autre support (papier/électronique) et les titres
    précédents/suivants sont retrouvés automatiquement via le Sudoc.
    « annee » accepte une année (2016) ou plusieurs (2016 2018) ou une plage (2016-2018).

Sources (webservices publics de l'ABES, sans clé) :
    https://www.sudoc.fr/services/issn2ppn/{issn}
    https://www.sudoc.fr/services/multiwhere/{ppn}
    https://www.sudoc.fr/{ppn}.xml   (UNIMARC, données locales 930/955/959 incluses)
    https://api.openalex.org/sources/issn:{issn}   (ISSN de l'autre support)

Liens suivis dans les notices :
    011 $f  ISSN-L (relie papier et électronique)
    452 $0  autre support
    430-437 $0 titres précédents, 440-448 $0 titres suivants (filtrés par dates de la zone 100)

Uniquement la bibliothèque standard Python.
"""
import argparse, csv, hashlib, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
import xml.etree.ElementTree as ET

BASE = "https://www.sudoc.fr"
UA = {"User-Agent": "reperio/0.3 (+https://github.com/guillaumegodet/reperio)"}
RCR_NANTES = "44109"          # RCR = code INSEE de la commune (44109 = Nantes) + 4 chiffres
PAUSE = 0.3                   # politesse envers les serveurs de l'ABES
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache_sudoc")
CACHE_TTL = 7 * 24 * 3600     # une semaine
PROFONDEUR_TITRES = 3         # nb max de changements de titre suivis dans chaque sens
UTILISER_CACHE = True

# Zone 930 $j : code PEB de l'exemplaire (référentiel ABES).
# Sources : ABES, « Modification des formats d'échange UNIMARC dans le Sudoc » (2022) ;
# règles ABES de saisie des données d'exemplaires des publications en série.
# Sans code : le Sudoc considère l'exemplaire comme disponible pour le PEB.
CODES_PEB = {
    "u": "disponible pour le PEB",
    "f": "reproduction seulement",
    "s": "PEB soumis à condition",
    "g": "non disponible pour le PEB",
    "v": "disponible sous forme électronique (libellé à confirmer)",
    "": "disponible pour le PEB (pas de code)",
}
RANG_PEB = {"u": 0, "": 0, "f": 1, "v": 1, "s": 2, "g": 9}

# Repérage des centres hospitaliers d'après le nom court (heuristique, à affiner).
RE_HOPITAL = re.compile(
    r"\bCH\b|\bCHU\b|\bCHR\b|\bCHI\b|\bCHS\b|\bHCL\b|APHP|AP-HP|H\.\s?Univ|Hôp|Hop\.|"
    r"Centre Hospitalier|Clinique|Clin\.|\bCLCC\b|Inst\. Curie|Gustave Roussy",
    re.I)


# --------------------------------------------------------------------------- accès réseau

def _chemin_cache(url):
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".txt")


def _cle_openalex():
    """Clé d'API OpenAlex : variable OPENALEX_API_KEY, sinon fichier .env à côté des scripts
    (ignoré par git : le dépôt est public). Chaîne vide si aucune clé."""
    cle = os.environ.get("OPENALEX_API_KEY", "").strip()
    if cle:
        return cle
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), encoding="utf-8") as f:
            for ligne in f:
                nom, _, valeur = ligne.partition("=")
                if nom.strip().removeprefix("export ").strip() == "OPENALEX_API_KEY":
                    return valeur.strip().strip("'\"")
    except OSError:
        pass
    return ""


OPENALEX_API_KEY = _cle_openalex()


def _telecharger_urllib(url):
    """(code HTTP, texte). Lève OSError si le serveur ne répond pas.
    La clé OpenAlex est ajoutée ici, après le calcul du cache : elle n'entre ni dans le cache
    ni dans les messages d'erreur, et la page web (autre transport) ne l'envoie jamais."""
    if OPENALEX_API_KEY and url.startswith("https://api.openalex.org/"):
        url += ("&" if "?" in url else "?") + "api_key=" + urllib.parse.quote(OPENALEX_API_KEY)
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, ""


# Transport HTTP : urllib en ligne de commande ; la page web (web/worker.js) le remplace
# par une requête du navigateur.
TELECHARGER = _telecharger_urllib


# Réponses de la session en cours (préchargées en parallèle, ou déjà lues) : évite de refaire
# une requête, même quand le cache disque est désactivé.
_MEMOIRE = {}


def _memoriser(url, txt):
    _MEMOIRE[url] = txt
    if UTILISER_CACHE:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_chemin_cache(url), "w", encoding="utf-8") as f:
            f.write(txt)


def deposer(url, code, texte):
    """Enregistre une réponse obtenue ailleurs (la page web la télécharge en parallèle).
    Seules les réponses définitives sont gardées : 2xx et 404."""
    if 200 <= code < 300:
        _memoriser(url, texte or "")
    elif code == 404:
        _memoriser(url, "")


def _en_cache(url):
    if url in _MEMOIRE:
        return True
    chemin = _chemin_cache(url)
    return UTILISER_CACHE and os.path.exists(chemin) and time.time() - os.path.getmtime(chemin) < CACHE_TTL


def a_telecharger(urls):
    """URL absentes du cache (mémoire ou disque), sans doublon."""
    return [u for u in dict.fromkeys(urls) if not _en_cache(u)]


def precharger(urls, travailleurs=8):
    """Télécharge en parallèle les URL absentes du cache (ligne de commande). Sans threads
    (navigateur), ne fait rien : get() les lira une à une, ou la page les aura déposées."""
    a_faire = a_telecharger(urls)
    if len(a_faire) < 2:
        return
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(travailleurs) as ex:
            list(ex.map(_get_silencieux, a_faire))
    except RuntimeError:
        pass


def _get_silencieux(url):
    try:
        get(url)
    except RuntimeError:
        pass


def get(url):
    """Renvoie le texte de la réponse, ou None si 404. Met en cache (mémoire et disque)."""
    if url in _MEMOIRE:
        return _MEMOIRE[url] or None
    chemin = _chemin_cache(url)
    if UTILISER_CACHE and os.path.exists(chemin) and time.time() - os.path.getmtime(chemin) < CACHE_TTL:
        with open(chemin, encoding="utf-8") as f:
            txt = f.read()
        _MEMOIRE[url] = txt
        return txt or None
    txt = None
    for essai in range(3):
        try:
            code, corps = TELECHARGER(url)
        except OSError:
            time.sleep(2 * (essai + 1))
            continue
        if 200 <= code < 300:
            time.sleep(PAUSE)
            txt = corps
            break
        if code == 404:
            txt = ""
            break
        time.sleep(2 * (essai + 1))
    else:
        raise RuntimeError(f"Échec : {url}")
    _memoriser(url, txt)
    return txt or None


def as_list(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def issn2ppn(issn):
    txt = get(f"{BASE}/services/issn2ppn/{issn}&format=text/json")
    if not txt:
        return []
    res = json.loads(txt)["sudoc"]["query"].get("result", [])
    return [r["ppn"] for r in as_list(res)]


def issns_openalex(issn):
    """Tous les ISSN (papier, électronique) connus d'OpenAlex pour la revue. [] en cas d'échec."""
    try:
        txt = get(f"https://api.openalex.org/sources/issn:{issn}?select=issn,issn_l")
    except RuntimeError:
        return []
    if not txt:
        return []
    d = json.loads(txt)
    return sorted(set(as_list(d.get("issn")) + as_list(d.get("issn_l"))))


def noms_bibliotheques(ppn):
    txt = get(f"{BASE}/services/multiwhere/{ppn}&format=text/json")
    if not txt:
        return {}
    libs = json.loads(txt)["sudoc"]["query"]["result"].get("library", [])
    return {l["rcr"]: l.get("shortname", "") for l in as_list(libs)}


# --------------------------------------------------------------------------- lecture des notices

def _int(s):
    try:
        return int(s.strip()[:4])
    except (ValueError, AttributeError):
        return None


def _liens(root, tags):
    return [s.text.strip() for df in root.findall("datafield") if df.get("tag") in tags
            for s in df.findall("subfield") if s.get("code") == "0" and s.text]


def parse_notice(xml_txt):
    """Renvoie un dict : titre, support, dates, liens, notes, exemplaires {epn: ...}."""
    root = ET.fromstring(xml_txt)
    c008 = root.findtext("controlfield[@tag='008']") or ""
    n = {
        "titre": root.findtext("datafield[@tag='200']/subfield[@code='a']") or "",
        "support": "électronique" if c008.startswith("O") else "papier",
        "issn": root.findtext("datafield[@tag='011']/subfield[@code='a']") or "",
        "issn_l": root.findtext("datafield[@tag='011']/subfield[@code='f']") or "",
        "autre_support": _liens(root, {"452"}),
        "precedents": _liens(root, {str(t) for t in range(430, 438)}),
        "suivants": _liens(root, {str(t) for t in range(440, 449)}),
        "debut": None, "fin": None, "e_only": None,
    }
    # Zone 100, positions 8-16 : type de date, date 1 (début), date 2 (fin ; 9999 = en cours)
    c100 = root.findtext("datafield[@tag='100']/subfield[@code='a']") or ""
    if len(c100) >= 17:
        n["debut"] = _int(c100[9:13])
        fin = _int(c100[13:17])
        n["fin"] = fin if fin and fin != 9999 else None
    # Notes 3XX : « devient e-only », « uniquement en ligne à partir de ... »
    for df in root.findall("datafield"):
        if df.get("tag", "").startswith("3"):
            note = " ".join(s.text or "" for s in df.findall("subfield"))
            m = re.search(r"(\d{4})[^.;]{0,40}?(e-only|uniquement (en ligne|électronique))", note, re.I) \
                or re.search(r"(?:e-only|uniquement (?:en ligne|électronique))[^.;]{0,40}?(\d{4})", note, re.I)
            if m:
                n["e_only"] = _int(m.group(1))

    ex = {}
    for df in root.findall("datafield"):
        tag = df.get("tag")
        if tag not in ("930", "955", "959"):
            continue
        sf = [(s.get("code"), (s.text or "").strip()) for s in df.findall("subfield")]
        epn = next((v for c, v in sf if c == "5"), None)
        if not epn:
            continue
        e = ex.setdefault(epn, {"rcr": epn.split(":")[0], "plages": [],
                                "manques": set(), "partiels": set(),
                                "etat": [], "pret": "", "cote": "",
                                "lacunes_signalees": False})
        if tag == "930":
            d = dict(sf)
            e["pret"], e["cote"] = d.get("j", ""), d.get("a", "")
        elif tag == "955":
            # Les $i successifs vont par paires : début, fin. $i vide = « -.... » (en cours)
            ans = [v for c, v in sf if c == "i"]
            for k in range(0, len(ans), 2):
                debut = _int(ans[k])
                if debut is None:
                    continue
                if k + 1 < len(ans):
                    fin = _int(ans[k + 1])
                    e["plages"].append((debut, fin if fin else None))   # None = ouvert
                else:
                    e["plages"].append((debut, debut))
            for c, v in sf:
                if c == "r":
                    e["etat"].append(v)
                if c == "w" and v:
                    e["lacunes_signalees"] = True
        elif tag == "959":
            # Occurrences séparées par $0. Sans $d/$e => année entière manquante.
            groupe = []
            for c, v in sf + [("0", "")]:
                if c == "0":
                    an = next((_int(x) for cc, x in groupe if cc == "a"), None)
                    if an:
                        if any(cc in ("d", "e") and x for cc, x in groupe):
                            e["partiels"].add(an)
                        else:
                            e["manques"].add(an)
                    groupe = []
                elif c != "r":
                    groupe.append((c, v))
    n["exemplaires"] = ex
    return n


_notices = {}


def notice(ppn):
    if ppn not in _notices:
        xml_txt = get(f"{BASE}/{ppn}.xml")
        _notices[ppn] = parse_notice(xml_txt) if xml_txt else None
    return _notices[ppn]


# --------------------------------------------------------------------------- famille de notices

def famille(issns, annees):
    """Rassemble les PPN utiles : ISSN donnés, ISSN-L, autre support, titres liés.
    Renvoie {ppn: (origine, debut_estime, fin_estimee)}.
    Les dates estimées complètent la zone 100 quand elle manque : un titre précédent se
    termine au plus tard quand commence son successeur, et inversement."""
    a_min, a_max = min(annees), max(annees)
    trouves = {}
    file = []          # (ppn, origine, profondeur_titres)

    def ajouter(ppn, origine, prof, debut=None, fin=None):
        if ppn not in trouves:
            trouves[ppn] = [origine, debut, fin]
            file.append((ppn, origine, prof))
        else:   # resserrer les estimations si un autre chemin en apporte
            t = trouves[ppn]
            if debut and (t[1] is None or debut > t[1]):
                t[1] = debut
            if fin and (t[2] is None or fin < t[2]):
                t[2] = fin

    for issn in issns:
        for ppn in issn2ppn(issn):
            ajouter(ppn, "ISSN demandé", 0)
        for autre in issns_openalex(issn):
            if autre not in issns:
                for ppn in issn2ppn(autre):
                    ajouter(ppn, "autre support (OpenAlex)", 0)

    while file:
        ppn, origine, prof = file.pop(0)
        n = notice(ppn)
        if not n:
            continue
        # Dates connues (zone 100) ou estimées ; transmises à l'autre support du même titre
        debut = n["debut"] or trouves[ppn][1]
        fin = n["fin"] or trouves[ppn][2]
        if n["issn_l"]:
            for p in issn2ppn(n["issn_l"]):
                ajouter(p, origine if origine != "ISSN demandé" else "autre support (ISSN-L)", prof, debut, fin)
        for p in n["autre_support"]:
            ajouter(p, origine if origine != "ISSN demandé" else "autre support", prof, debut, fin)
        if prof < PROFONDEUR_TITRES:
            # On ne remonte vers le titre précédent que si la notice commence après l'année cherchée
            if debut is None or debut > a_min:
                for p in n["precedents"]:
                    ajouter(p, "titre précédent", prof + 1, fin=debut)
            if fin is not None and fin < a_max:
                for p in n["suivants"]:
                    ajouter(p, "titre suivant", prof + 1, debut=fin)
    return {p: tuple(t) for p, t in trouves.items() if notice(p)}


# --------------------------------------------------------------------------- statut

def statut(e, annee, n, origine="ISSN demandé", debut=None, fin=None):
    """Renvoie (statut, confiance) ou None si l'année n'est pas couverte.
    debut/fin : dates de publication du titre (zone 100, sinon estimées par famille())."""
    couvre = [(d, f) for d, f in e["plages"] if d <= annee and (f is None or annee <= f)]
    if not couvre or annee in e["manques"]:
        return None
    if (debut and annee < debut) or (fin and annee > fin):
        return None          # le titre ne paraissait pas sous ce nom cette année-là
    if annee in e["partiels"]:
        return "lacunaire (numéros manquants)", "moyenne"
    if all(f is None for _, f in couvre):
        if n["support"] == "papier" and n["e_only"] and annee >= n["e_only"]:
            return f"douteux (titre e-only depuis {n['e_only']})", "faible"
        if origine.startswith("titre") and fin is None:
            return "douteux (état ouvert sur un ancien titre)", "faible"
        if origine == "titre précédent" and annee == fin:
            return "douteux (année du changement de titre)", "faible"
        return "oui (état ouvert, à confirmer)", "moyenne"
    if e["lacunes_signalees"] and not (e["manques"] or e["partiels"]):
        return "oui (lacunes non détaillées)", "moyenne"
    return "oui", "haute"


ORDRE_STATUT = {"oui": 0, "oui (lacunes non détaillées)": 1,
                "oui (état ouvert, à confirmer)": 2, "lacunaire (numéros manquants)": 3}


def type_bib(nom):
    return "hôpital" if RE_HOPITAL.search(nom or "") else "BU / autre"


def rechercher(libelle, issns, annees, sans_hopitaux=False):
    lignes = []
    fam = famille(issns, annees)
    noms = {}
    for ppn, (origine, debut_est, fin_est) in fam.items():
        n = notice(ppn)
        if not n["exemplaires"]:
            continue
        debut, fin = n["debut"] or debut_est, n["fin"] or fin_est
        for annee in annees:
            for e in n["exemplaires"].values():
                r = statut(e, annee, n, origine, debut, fin)
                if not r:
                    continue
                if ppn not in noms:
                    noms[ppn] = noms_bibliotheques(ppn)
                nom = noms[ppn].get(e["rcr"], "")
                tb = type_bib(nom)
                if sans_hopitaux and tb == "hôpital":
                    continue
                lignes.append({
                    "demande": libelle, "annee": annee, "statut": r[0], "confiance": r[1],
                    "bibliotheque": nom, "type": tb, "rcr": e["rcr"],
                    "nantes": "oui" if e["rcr"].startswith(RCR_NANTES) else "",
                    "support": n["support"],
                    "peb": CODES_PEB.get(e["pret"], f"code inconnu ({e['pret']})"),
                    "code_peb_930j": e["pret"],
                    "cote": e["cote"], "etat_collection": " ; ".join(e["etat"]),
                    "ppn": ppn, "titre_sudoc": n["titre"], "lien": origine,
                    "source": "Sudoc",
                })
    lignes.sort(key=lambda l: (l["annee"], l["support"] != "papier",
                               RANG_PEB.get(l["code_peb_930j"], 5) >= 9,
                               ORDRE_STATUT.get(l["statut"], 8),
                               RANG_PEB.get(l["code_peb_930j"], 5), l["bibliotheque"]))
    return lignes


def issns_utiles(issns, annee):
    """ISSN de tous les titres de la famille qui paraissaient l'année demandée
    (pour interroger les sources électroniques avec le bon ISSN, y compris un ancien titre)."""
    res = list(issns)
    for ppn, (origine, debut_est, fin_est) in famille(issns, [annee]).items():
        n = notice(ppn)
        debut, fin = n["debut"] or debut_est, n["fin"] or fin_est
        if (debut and annee < debut) or (fin and annee > fin):
            continue
        for i in (n["issn"], n["issn_l"]):
            if i and i not in res:
                res.append(i)
    return res


def lire_annees(s):
    annees = []
    for morceau in s.replace(",", " ").split():
        if re.fullmatch(r"\d{4}-\d{4}", morceau):
            d, f = map(int, morceau.split("-"))
            annees += range(d, f + 1)
        else:
            annees.append(int(morceau))
    return sorted(set(annees))


def main():
    global UTILISER_CACHE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="fichier libelle;issn;annee")
    ap.add_argument("--issn", nargs="+")
    ap.add_argument("--annee", help="2016, « 2016 2018 » ou 2016-2018")
    ap.add_argument("--sortie", default="resultats_peb.csv")
    ap.add_argument("--sans-hopitaux", action="store_true", help="exclure les centres hospitaliers")
    ap.add_argument("--sans-cache", action="store_true", help="ignorer et ne pas écrire le cache")
    a = ap.parse_args()
    UTILISER_CACHE = not a.sans_cache

    demandes = []
    if a.csv:
        with open(a.csv, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f, delimiter=";"):
                demandes.append((r["libelle"], r["issn"].split(), lire_annees(r["annee"])))
    elif a.issn and a.annee:
        demandes.append((" / ".join(a.issn), a.issn, lire_annees(a.annee)))
    else:
        ap.error("donner un CSV ou --issn ... --annee ...")

    toutes = []
    for libelle, issns, annees in demandes:
        res = rechercher(libelle, issns, annees, a.sans_hopitaux)
        for annee in annees:
            sel = [l for l in res if l["annee"] == annee]
            sures = sum(l["confiance"] == "haute" for l in sel)
            print(f"\n== {libelle} — {annee} : {len(sel)} localisation(s), dont {sures} sûre(s)")
            for l in sel:
                print(f"  [{l['support'][:4]}] {l['statut']:<34} {l['bibliotheque'][:32]:<33}"
                      f" {l['peb'][:26]:<27} {l['etat_collection'][:50]}")
        toutes += res

    if toutes:
        with open(a.sortie, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(toutes[0]), delimiter=";")
            w.writeheader()
            w.writerows(toutes)
        print(f"\n-> {a.sortie} ({len(toutes)} lignes)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
