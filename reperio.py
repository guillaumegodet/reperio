#!/usr/bin/env python3
"""
reperio.py — Repério : pour une revue et une année, où la trouver pour le PEB ?

Enchaîne :
    étape 0  déjà accessible à Nantes Université ? (export HLM du catalogue Nantilus, peb_nantes.py)
    phase 2  accès sans PEB : libre accès (OpenAlex, DOAJ), Licences nationales (BACON), ISTEX
    phase 1  états de collection du Sudoc (papier et électronique)
    phase 3  résolveurs de liens des BU prioritaires (resolveurs.csv)
et produit un tableau unique trié (CSV) et une page HTML pour l'équipe PEB.

Usage :
    python reperio.py demandes.csv                       -> resultats_reperio.csv + rapport_reperio.html
    python reperio.py --issn 0008-6568 --annee 2016
    options : --sans-hopitaux  --sans-cache  --sortie fichier.csv  --html fichier.html
"""
import argparse, csv, datetime, html, os, sys, time
import peb_sudoc, peb_acces, peb_resolveurs, peb_nantes

ICI = os.path.dirname(os.path.abspath(__file__))
COLONNES = ["demande", "annee", "statut", "confiance", "bibliotheque", "type", "rcr", "prioritaire",
            "support", "couverture", "peb", "source", "detail", "url"]
RANG_CONFIANCE = {"haute": 0, "moyenne": 1, "faible": 2}


def rcr_prioritaires():
    try:
        return {c["rcr"] for c in peb_resolveurs.charger_config()
                if c["rcr"] and c.get("prioritaire", "oui") == "oui"}
    except FileNotFoundError:
        return set()


def lignes_sudoc(libelle, issns, annee, sans_hopitaux, prio):
    res = []
    for l in peb_sudoc.rechercher(libelle, issns, [annee], sans_hopitaux):
        detail = " ; ".join(x for x in (
            f"cote {l['cote']}" if l["cote"] else "",
            f"trouvé via {l['lien']}" if l["lien"] != "ISSN demandé" else "",
            l["titre_sudoc"] if l["lien"].startswith("titre") else "") if x)
        res.append({
            "demande": libelle, "annee": annee, "statut": l["statut"], "confiance": l["confiance"],
            "bibliotheque": l["bibliotheque"], "type": l["type"], "rcr": l["rcr"],
            "prioritaire": "oui" if l["rcr"] in prio else ("Nantes" if l["nantes"] else ""),
            "support": l["support"], "couverture": l["etat_collection"], "peb": l["peb"],
            "source": "Sudoc", "detail": detail, "url": f"https://www.sudoc.fr/{l['ppn']}",
        })
    return res


def cle_tri(l):
    pret = 9 if l["peb"].startswith("non disponible") else 0
    return (RANG_CONFIANCE.get(l["confiance"], 3), pret, l["prioritaire"] != "oui",
            l["support"] != "papier", l["bibliotheque"])


def traiter_par_etapes(libelle, issns, annee, sans_hopitaux, prio):
    """Générateur : s'arrête une fois sur la liste des requêtes aux résolveurs, pour que l'appelant
    les télécharge en parallèle (threads en ligne de commande, fetch dans la page web),
    puis renvoie le résultat (StopIteration.value)."""
    t0 = time.time()
    tous_issns = peb_sudoc.issns_utiles(issns, annee)
    yield peb_resolveurs.urls(tous_issns, annee)
    verdict_nantes, nantes = peb_nantes.evaluer(libelle, tous_issns, annee)
    verdict, acces = peb_acces.evaluer(libelle, tous_issns, annee)
    sudoc = lignes_sudoc(libelle, issns, annee, sans_hopitaux, prio)
    resolveurs, etat = peb_resolveurs.interroger(libelle, tous_issns, annee)
    localisations = sorted(sudoc + resolveurs, key=cle_tri)
    return {"libelle": libelle, "annee": annee, "issns": tous_issns, "verdict_nantes": verdict_nantes,
            "nantes": nantes, "verdict": verdict,
            "acces": acces, "localisations": localisations, "etat": etat,
            "a_consulter": peb_resolveurs.a_consulter(issns[0] if issns else tous_issns[0]),
            "duree": time.time() - t0}


# --------------------------------------------------------------------------- rapport HTML

CSS = """
:root{--bg:#fbfaf7;--fg:#1f2328;--muted:#5f6670;--line:#e3e1db;--card:#fff;--ok:#1a7f37;--okbg:#e9f6ec;
--warn:#9a6700;--warnbg:#fff6dc;--bad:#b42318;--chip:#f0eee8;--accent:#2f5d8a}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e6e6e3;--muted:#9aa0a8;--line:#30343b;--card:#1d2026;
--ok:#56c271;--okbg:#17301f;--warn:#e3b341;--warnbg:#332a12;--bad:#ff7b72;--chip:#272b32;--accent:#79a8d8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.5rem;margin:0 0 4px}
.sous{color:var(--muted);margin:0 0 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin:0 0 24px}
h2{font-size:1.15rem;margin:0 0 6px}h3{font-size:1rem;margin:14px 0 6px}.issn{color:var(--muted);font-size:.85rem}
.verdict{border-radius:8px;padding:10px 14px;margin:12px 0}.verdict.ok{background:var(--okbg);color:var(--ok)}
.verdict.peb{background:var(--warnbg);color:var(--warn)}
.resume{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}.chip{background:var(--chip);border-radius:999px;padding:2px 10px;font-size:.85rem}
.filtres{display:flex;flex-wrap:wrap;gap:16px;margin:10px 0;font-size:.9rem;color:var(--muted)}
.tab{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:0;background:var(--card);font-weight:600}
td.c-haute{color:var(--ok);font-weight:600}td.c-moyenne{color:var(--warn)}td.c-faible{color:var(--bad)}
tr.prio td:first-child{border-left:3px solid var(--accent)}a{color:var(--accent)}
details{margin-top:10px}summary{cursor:pointer;color:var(--muted)}.muted{color:var(--muted)}
"""

JS = """
document.querySelectorAll('section').forEach(function(s){
  var f=s.querySelectorAll('.filtres input');
  function maj(){var p=f[0].checked,d=f[1].checked;
    s.querySelectorAll('tbody.loc tr').forEach(function(tr){
      var cache=(p&&!tr.classList.contains('prio'))||(d&&tr.dataset.conf==='faible');
      tr.style.display=cache?'none':'';});}
  f.forEach(function(i){i.addEventListener('change',maj)});maj();});
"""


def _e(s):
    return html.escape(str(s or ""))


def _lien(l):
    return f'<a href="{_e(l["url"])}" target="_blank" rel="noopener">{_e(l["source"])}</a>' if l["url"] else _e(l["source"])


def rapport_html(resultats, chemin):
    parts = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>Repério</title>"
             f"<style>{CSS}</style></head><body><main><h1>Repério — localisations pour le PEB</h1>"
             f"<p class='sous'>Généré le {datetime.datetime.now():%d/%m/%Y à %H:%M} · sources : {_e(peb_nantes.etat()[1])}, Sudoc, "
             f"résolveurs Alma des BU prioritaires, OpenAlex, BACON, ISTEX. "
             f"Bordure bleue = BU prioritaire. Confiance : <b>haute</b> = état fermé ou résolveur à jour ; "
             f"<b>moyenne</b> = état ouvert à confirmer ; <b>faible</b> = douteux.</p>"]
    for r in resultats:
        locs = r["localisations"]
        sures = sum(l["confiance"] == "haute" for l in locs)
        prios = sum(l["prioritaire"] == "oui" for l in locs)
        papier = sum(l["support"] == "papier" for l in locs)
        parts.append(f"<section><h2>{_e(r['libelle'])} — {r['annee']}</h2>"
                     f"<div class='issn'>ISSN interrogés : {_e(', '.join(r['issns']))}</div>")
        if r["verdict_nantes"]:
            parts.append(f"<div class='verdict ok'><b>Déjà accessible à Nantes Université, pas de PEB :</b> "
                         f"{_e(r['verdict_nantes'][len('accessible à Nantes Université : '):])}</div>")
        if r["verdict"]:
            parts.append(f"<div class='verdict ok'><b>Accessible sans PEB probable :</b> {_e(r['verdict'])}</div>")
        elif not r["verdict_nantes"]:
            parts.append("<div class='verdict peb'><b>Pas d'accès libre ou national trouvé</b> → PEB</div>")
        if r["nantes"]:
            parts.append("<h3>Ressources électroniques de Nantes Université</h3><div class='tab'><table><thead><tr>"
                         "<th>Bouquet</th><th>Statut</th><th>Confiance</th><th>Couverture</th><th>Catalogue</th>"
                         "<th>Détail</th></tr></thead><tbody>")
            for l in r["nantes"]:
                parts.append(f"<tr><td>{_e(l['bibliotheque'].split(' — ', 1)[-1])}</td><td>{_e(l['statut'])}</td>"
                             f"<td class='c-{_e(l['confiance'])}'>{_e(l['confiance'])}</td><td>{_e(l['couverture'])}</td>"
                             f"<td>{_lien(dict(l, source='Nantilus'))}</td><td class='muted'>{_e(l['detail'])}</td></tr>")
            parts.append("</tbody></table></div>")
        parts.append(f"<div class='resume'><span class='chip'>{len(locs)} localisations</span>"
                     f"<span class='chip'>{sures} sûres</span><span class='chip'>{papier} papier</span>"
                     f"<span class='chip'>{prios} BU prioritaires</span>"
                     f"<span class='chip'>{r['duree']:.0f} s</span></div>")
        parts.append("<div class='filtres'><label><input type='checkbox'> BU prioritaires seulement</label>"
                     "<label><input type='checkbox' checked> masquer les localisations douteuses</label></div>")
        parts.append("<div class='tab'><table><thead><tr><th>Bibliothèque</th><th>Statut</th><th>Confiance</th>"
                     "<th>Support</th><th>Couverture</th><th>PEB</th><th>Source</th><th>Détail</th></tr></thead>"
                     "<tbody class='loc'>")
        for l in locs:
            cls = "prio" if l["prioritaire"] == "oui" else ""
            nom = _e(l["bibliotheque"]) + (" <span class='muted'>(Nantes)</span>" if l["prioritaire"] == "Nantes" else "")
            parts.append(f"<tr class='{cls}' data-conf='{_e(l['confiance'])}'><td>{nom}</td><td>{_e(l['statut'])}</td>"
                         f"<td class='c-{_e(l['confiance'])}'>{_e(l['confiance'])}</td><td>{_e(l['support'])}</td>"
                         f"<td>{_e(l['couverture'])}</td><td>{_e(l['peb'])}</td><td>{_lien(l)}</td>"
                         f"<td class='muted'>{_e(l['detail'])}</td></tr>")
        if not locs:
            parts.append("<tr><td colspan='8' class='muted'>Aucune localisation trouvée.</td></tr>")
        parts.append("</tbody></table></div>")
        if r["acces"]:
            parts.append(f"<details><summary>Accès en ligne et bouquets ({len(r['acces'])})</summary>"
                         "<div class='tab'><table><thead><tr><th>Accès</th><th>Statut</th><th>Couverture</th>"
                         "<th>Source</th><th>Détail</th></tr></thead><tbody>")
            for l in sorted(r["acces"], key=lambda l: RANG_CONFIANCE.get(l["confiance"], 3)):
                parts.append(f"<tr><td>{_e(l['bibliotheque'])}</td><td>{_e(l['statut'])}</td>"
                             f"<td>{_e(l['couverture'])}</td><td>{_lien(l)}</td><td class='muted'>{_e(l['detail'])}</td></tr>")
            parts.append("</tbody></table></div></details>")
        manuels = r.get("a_consulter") or []
        if manuels:
            noms = {"ebsco": "EBSCO", "summon": "Summon", "sebina": "SebinaYOU"}
            parts.append(f"<details><summary>Catalogues à consulter à la main ({len(manuels)})</summary>"
                         "<p class='muted'>Pas de résolveur interrogeable : le lien ouvre le catalogue, "
                         "recherche par ISSN déjà remplie quand le catalogue le permet.</p><ul>")
            for m in manuels:
                parts.append(f"<li><a href='{_e(m['url'])}' target='_blank' rel='noopener'>{_e(m['etablissement'])}</a>"
                             f" <span class='muted'>{_e(noms.get(m['systeme'], ''))}</span></li>")
            parts.append("</ul></details>")
        non = [f"{k} ({v})" for k, v in r["etat"].items() if v != "interrogé"]
        if non:
            parts.append(f"<details><summary>BU prioritaires non interrogées automatiquement ({len(non)})</summary>"
                         f"<p class='muted'>{_e(', '.join(non))}</p></details>")
        parts.append("</section>")
    parts.append(f"</main><script>{JS}</script></body></html>")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("".join(parts))


def lire_demandes(lignes):
    """Demandes « libelle;issn;annee » : point-virgule, ou tabulation (copier-coller depuis Excel).
    L'en-tête est facultatif ; sans en-tête, une ligne de 2 colonnes se lit « issn;annee ».
    Renvoie [(libellé, [issn], [années])]."""
    lignes = [l.lstrip("\ufeff") for l in (x.rstrip("\r\n") for x in lignes) if l.strip()]
    if not lignes:
        return []
    sep = "\t" if "\t" in lignes[0] else ";"
    rangs = list(csv.reader(lignes, delimiter=sep))
    entete = [c.strip().lower() for c in rangs[0]]
    if "issn" in entete and "annee" in entete:
        rangs = [dict(zip(entete, r)) for r in rangs[1:]]
    else:
        lues = []
        for r in rangs:
            cellules = [c for c in r if c.strip()]
            cles = ("issn", "annee") if len(cellules) == 2 else ("libelle", "issn", "annee")
            lues.append(dict(zip(cles, cellules if len(cellules) == 2 else r)))
        rangs = lues
    demandes = []
    for n, r in enumerate(rangs, 1):
        r = {k: (v or "").strip() for k, v in r.items()}
        issns = r.get("issn", "").replace(",", " ").split()
        try:
            annees = peb_sudoc.lire_annees(r.get("annee", ""))
        except ValueError:
            annees = []
        if not (issns and annees):
            print(f"Ligne {n} ignorée (ISSN ou année illisible) : {sep.join(r.values())}", flush=True)
            continue
        demandes.append((r.get("libelle") or " / ".join(issns), issns, annees))
    return demandes


def traiter(libelle, issns, annee, sans_hopitaux, prio):
    etapes = traiter_par_etapes(libelle, issns, annee, sans_hopitaux, prio)
    peb_sudoc.precharger(next(etapes))
    try:
        next(etapes)
    except StopIteration as fin:
        return fin.value


def executer_par_etapes(demandes, sans_hopitaux=False):
    """Traite toutes les demandes ; affiche l'avancement au fil de l'eau. Générateur : produit les
    listes d'URL à précharger, renvoie la liste des résultats (voir traiter_par_etapes)."""
    prio = rcr_prioritaires()
    resultats = []
    total = sum(len(annees) for _, _, annees in demandes)
    for libelle, issns, annees in demandes:
        for annee in annees:
            print(f"\n[{len(resultats) + 1}/{total}] {libelle} — {annee} : recherche…", flush=True)
            r = yield from traiter_par_etapes(libelle, issns, annee, sans_hopitaux, prio)
            resultats.append(r)
            locs = r["localisations"]
            print(f"== {libelle} — {annee}  ({r['duree']:.0f} s)")
            print("   Nantes :", r["verdict_nantes"] or "pas d'accès électronique trouvé")
            print("   Accès sans PEB :", r["verdict"] or "non trouvé")
            print(f"   {len(locs)} localisations, {sum(l['confiance'] == 'haute' for l in locs)} sûres, "
                  f"{sum(l['prioritaire'] == 'oui' for l in locs)} en BU prioritaire")
            for l in [l for l in locs if l["confiance"] != "faible"][:8]:
                print(f"     [{l['support'][:4]}] {l['confiance']:<8} {l['bibliotheque'][:40]:<41} {l['peb'][:24]:<25} {l['source']}",
                      flush=True)
    return resultats


def executer(demandes, sans_hopitaux=False):
    etapes = executer_par_etapes(demandes, sans_hopitaux)
    try:
        while True:
            peb_sudoc.precharger(next(etapes))
    except StopIteration as fin:
        return fin.value


def ecrire_csv(resultats, chemin):
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in resultats:
            w.writerows(r["nantes"])
            w.writerows(r["acces"])
            w.writerows(r["localisations"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="fichier libelle;issn;annee")
    ap.add_argument("--issn", nargs="+")
    ap.add_argument("--annee", help="2016, « 2016 2018 » ou 2016-2018")
    ap.add_argument("--sortie", default=os.path.join(ICI, "resultats_reperio.csv"))
    ap.add_argument("--html", default=os.path.join(ICI, "rapport_reperio.html"))
    ap.add_argument("--sans-hopitaux", action="store_true")
    ap.add_argument("--sans-cache", action="store_true")
    a = ap.parse_args()
    peb_sudoc.UTILISER_CACHE = not a.sans_cache

    if a.csv:
        with open(a.csv, encoding="utf-8-sig") as f:
            demandes = lire_demandes(f)
    elif a.issn and a.annee:
        demandes = [(" / ".join(a.issn), a.issn, peb_sudoc.lire_annees(a.annee))]
    else:
        ap.error("donner un CSV ou --issn ... --annee ...")

    resultats = executer(demandes, a.sans_hopitaux)
    ecrire_csv(resultats, a.sortie)
    rapport_html(resultats, a.html)
    print(f"\n-> {a.sortie}\n-> {a.html}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
