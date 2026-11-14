/* Repério dans le navigateur : ce worker fait tourner le code Python du dépôt avec Pyodide.
   Les fichiers .py sont servis à côté de la page (dossier py/, assemblé par le workflow Pages).
   Les requêtes HTTP partent du navigateur (XMLHttpRequest synchrone, permis dans un worker). */
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const FICHIERS = ["peb_sudoc.py", "peb_acces.py", "peb_resolveurs.py", "peb_nantes.py", "reperio.py",
                  "resolveurs.csv"];
const DOSSIER = "/home/pyodide/reperio";
const INDEX = DOSSIER + "/donnees/fonds_nantes.json.gz";

importScripts(PYODIDE + "pyodide.js");

let py = null;

function syncfs(lire) {
  return new Promise((ok, ko) => py.FS.syncfs(lire, (e) => (e ? ko(e) : ok())));
}

const AMORCE = `
import os, sys, time
sys.path.insert(0, ${JSON.stringify(DOSSIER)})
os.chdir(${JSON.stringify(DOSSIER)})
from js import XMLHttpRequest

def _xhr(url):
    r = XMLHttpRequest.new()
    r.open("GET", url, False)
    r.timeout = 30000
    try:
        r.send(None)
    except Exception as e:
        raise OSError(str(e))
    if r.status == 0:
        raise OSError("pas de réponse")
    return r.status, r.responseText

def _attendre(s):
    # time.sleep ne suspend pas un worker Pyodide : attente active, limitée aux pauses de politesse
    fin = time.monotonic() + s
    while time.monotonic() < fin:
        pass

time.sleep = _attendre
import peb_sudoc, peb_nantes, reperio
peb_sudoc.TELECHARGER = _xhr

def etat_index():
    peb_nantes._CHARGE.clear()
    return peb_nantes.etat()[1]

def lancer(texte, sans_hopitaux, sans_cache):
    peb_sudoc.UTILISER_CACHE = not sans_cache
    demandes = reperio.lire_demandes(texte.splitlines())
    if not demandes:
        raise ValueError("Aucune demande lisible : il faut au moins un ISSN et une année.")
    res = reperio.executer(demandes, sans_hopitaux)
    reperio.rapport_html(res, "/tmp/rapport.html")
    reperio.ecrire_csv(res, "/tmp/resultats.csv")
    return (open("/tmp/rapport.html", encoding="utf-8").read(),
            open("/tmp/resultats.csv", encoding="utf-8").read(), len(res))
`;

async function initialiser() {
  py = await loadPyodide({ indexURL: PYODIDE });
  py.setStdout({ batched: (s) => postMessage({ type: "journal", texte: s }) });
  py.setStderr({ batched: (s) => postMessage({ type: "journal", texte: s }) });
  py.FS.mkdirTree(DOSSIER + "/donnees");
  // Cache des réponses (une semaine) gardé dans le navigateur d'une visite à l'autre
  py.FS.mkdirTree(DOSSIER + "/.cache_sudoc");
  py.FS.mount(py.FS.filesystems.IDBFS, {}, DOSSIER + "/.cache_sudoc");
  await syncfs(true).catch(() => {});
  const base = new URL("py/", self.location.href);
  for (const nom of FICHIERS) {
    const r = await fetch(new URL(nom, base), { cache: "no-cache" });
    if (!r.ok) throw new Error(`fichier ${nom} introuvable (${r.status})`);
    py.FS.writeFile(DOSSIER + "/" + nom, new Uint8Array(await r.arrayBuffer()));
  }
  await py.runPythonAsync(AMORCE);
}

function etatIndex() {
  return py.globals.get("etat_index")();
}

const pret = initialiser();

onmessage = async (ev) => {
  const m = ev.data;
  try {
    await pret;
    if (m.type === "init") {
      postMessage({ type: "pret", index: etatIndex() });
    } else if (m.type === "index") {
      py.FS.writeFile(INDEX, new Uint8Array(m.contenu));
      const etat = etatIndex();
      if (etat.startsWith("index Nantilus absent")) throw new Error("fichier d'index illisible");
      postMessage({ type: "index", index: etat });
    } else if (m.type === "index-retirer") {
      try { py.FS.unlink(INDEX); } catch (e) { /* déjà absent */ }
      postMessage({ type: "index", index: etatIndex() });
    } else if (m.type === "lancer") {
      const lancer = py.globals.get("lancer");
      const res = lancer(m.texte, m.sansHopitaux, m.sansCache);
      const [html, csv, n] = res.toJs();
      res.destroy();
      await syncfs(false).catch(() => {});
      postMessage({ type: "resultat", html, csv, n });
    }
  } catch (e) {
    if (m.type === "index") {
      try { py.FS.unlink(INDEX); } catch (_) { /* rien */ }
    }
    postMessage({ type: "erreur", contexte: m.type, message: String(e && e.message || e) });
  }
};
