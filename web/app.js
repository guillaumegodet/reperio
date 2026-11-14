/* Repério — interface. Le calcul tourne dans worker.js (Pyodide). */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const worker = new Worker("worker.js");
  let pret = false, enCours = false, dernier = null, mode = "une";

  // ------------------------------------------------------------------ index Nantes (IndexedDB)
  const BASE = "reperio", MAGASIN = "fichiers", CLE = "fonds_nantes";

  function ouvrirBase() {
    return new Promise((ok, ko) => {
      const req = indexedDB.open(BASE, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(MAGASIN);
      req.onsuccess = () => ok(req.result);
      req.onerror = () => ko(req.error);
    });
  }
  async function stocker(valeur) {
    try {
      const db = await ouvrirBase();
      await new Promise((ok, ko) => {
        const tx = db.transaction(MAGASIN, "readwrite");
        if (valeur === null) tx.objectStore(MAGASIN).delete(CLE);
        else tx.objectStore(MAGASIN).put(valeur, CLE);
        tx.oncomplete = ok; tx.onerror = () => ko(tx.error);
      });
    } catch (e) { /* stockage indisponible (navigation privée) : l'index vaut pour la session */ }
  }
  async function relire() {
    try {
      const db = await ouvrirBase();
      return await new Promise((ok) => {
        const req = db.transaction(MAGASIN).objectStore(MAGASIN).get(CLE);
        req.onsuccess = () => ok(req.result || null);
        req.onerror = () => ok(null);
      });
    } catch (e) { return null; }
  }

  function afficherIndex(texte) {
    const absent = texte.startsWith("index Nantilus absent");
    $("etat-index").textContent = absent
      ? "Aucun index chargé : les abonnements de Nantes ne seront pas vérifiés."
      : "Index chargé : " + texte + ".";
    $("etat-index").className = "etat" + (absent ? "" : " ok");
    $("retirer-index").hidden = absent;
  }

  $("fichier-index").addEventListener("change", async (ev) => {
    const f = ev.target.files[0];
    ev.target.value = "";
    if (!f) return;
    const contenu = await f.arrayBuffer();
    const octets = new Uint8Array(contenu, 0, 2);
    if (octets[0] !== 0x1f || octets[1] !== 0x8b) {
      $("etat-index").textContent = "Ce fichier n'est pas l'index attendu (fonds_nantes.json.gz).";
      $("etat-index").className = "etat";
      return;
    }
    $("etat-index").textContent = "Lecture de l'index…";
    worker.postMessage({ type: "index", contenu: contenu.slice(0) });
    stocker(contenu);
  });
  $("retirer-index").addEventListener("click", () => {
    stocker(null);
    worker.postMessage({ type: "index-retirer" });
  });

  // ------------------------------------------------------------------ formulaire
  function choisirOnglet(m) {
    mode = m;
    $("o-une").setAttribute("aria-selected", String(m === "une"));
    $("o-liste").setAttribute("aria-selected", String(m === "liste"));
    $("p-une").hidden = m !== "une";
    $("p-liste").hidden = m !== "liste";
  }
  $("o-une").addEventListener("click", () => choisirOnglet("une"));
  $("o-liste").addEventListener("click", () => choisirOnglet("liste"));

  $("fichier-liste").addEventListener("change", async (ev) => {
    const f = ev.target.files[0];
    ev.target.value = "";
    if (f) $("liste").value = (await f.text()).replace(/^﻿/, "");
  });

  function texteDemandes() {
    if (mode === "liste") return $("liste").value;
    const issn = $("issn").value.trim().replace(/[;\t]/g, " ");
    const annee = $("annee").value.trim().replace(/[;\t]/g, " ");
    const libelle = $("libelle").value.trim().replace(/[;\t]/g, " ");
    if (!issn || !annee) return "";
    return "libelle;issn;annee\n" + (libelle || issn) + ";" + issn + ";" + annee;
  }

  function erreurFormulaire(msg) {
    $("erreur-form").textContent = msg || "";
    $("erreur-form").hidden = !msg;
  }

  $("formulaire").addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!pret || enCours) return;
    const texte = texteDemandes();
    if (!texte.trim()) {
      erreurFormulaire(mode === "une" ? "Indiquez un ISSN et une année." : "La liste est vide.");
      return;
    }
    const lignes = mode === "liste" ? texte.split(/\n/).filter((l) => l.trim()).length : 1;
    if (lignes > 50 && !confirm(lignes + " demandes : comptez plusieurs minutes. Continuer ?")) return;
    erreurFormulaire("");
    enCours = true;
    $("lancer").disabled = true;
    $("carte-suivi").hidden = false;
    $("journal").textContent = "";
    $("avancement").textContent = "Recherche en cours…";
    worker.postMessage({ type: "lancer", texte, sansHopitaux: $("sans-hopitaux").checked,
                         sansCache: $("sans-cache").checked });
  });

  // ------------------------------------------------------------------ résultats
  function telecharger(nom, contenu, type) {
    const url = URL.createObjectURL(new Blob([contenu], { type }));
    const a = Object.assign(document.createElement("a"), { href: url, download: nom });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function horodatage() {
    const d = new Date(), p = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "-" + p(d.getHours()) + p(d.getMinutes());
  }
  $("dl-csv").addEventListener("click", () => dernier &&
    telecharger("reperio-" + horodatage() + ".csv", dernier.csv, "text/csv;charset=utf-8"));
  $("dl-html").addEventListener("click", () => dernier &&
    telecharger("reperio-" + horodatage() + ".html", dernier.html, "text/html;charset=utf-8"));

  const cadre = $("rapport");
  let observateur = null;
  cadre.addEventListener("load", () => {
    const doc = cadre.contentDocument;
    if (!doc) return;
    // hauteur du contenu (body), pas celle du cadre : sinon le cadre grandirait sans fin
    const ajuster = () => { cadre.style.height = Math.ceil(doc.body.getBoundingClientRect().height) + 2 + "px"; };
    if (observateur) observateur.disconnect();
    observateur = new ResizeObserver(ajuster);
    observateur.observe(doc.body);
    ajuster();
  });

  // ------------------------------------------------------------------ messages du worker
  function derniereLigne(msg) {
    const l = msg.trim().split("\n").filter((x) => x.trim());
    return l.length ? l[l.length - 1] : msg;
  }

  worker.onmessage = (ev) => {
    const m = ev.data;
    if (m.type === "pret") {
      pret = true;
      $("lancer").disabled = false;
      afficherIndex(m.index);
    } else if (m.type === "index") {
      afficherIndex(m.index);
    } else if (m.type === "journal") {
      $("journal").textContent += m.texte + "\n";
      const prog = /^\[(\d+)\/(\d+)\] (.*) : recherche…$/.exec(m.texte);
      if (prog) $("avancement").textContent = "Demande " + prog[1] + " sur " + prog[2] + " : " + prog[3] + "…";
    } else if (m.type === "resultat") {
      enCours = false;
      $("lancer").disabled = false;
      dernier = { html: m.html, csv: "﻿" + m.csv.replace(/^﻿/, "") };
      $("avancement").textContent = m.n + (m.n > 1 ? " recherches terminées." : " recherche terminée.");
      $("resultats").hidden = false;
      cadre.srcdoc = m.html;
      $("resultats").scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (m.type === "erreur") {
      const msg = derniereLigne(m.message);
      if (m.contexte === "lancer") {
        enCours = false;
        $("lancer").disabled = false;
        $("avancement").textContent = "La recherche a échoué : " + msg;
      } else if (m.contexte === "index") {
        stocker(null);
        $("etat-index").textContent = "Index illisible : " + msg;
        $("etat-index").className = "etat";
      } else {
        $("etat-index").textContent = "Repério n'a pas pu démarrer : " + msg;
      }
    }
  };

  // ------------------------------------------------------------------ démarrage
  $("etat-index").textContent = "Chargement de Repério (environ 10 Mo la première fois)…";
  worker.postMessage({ type: "init" });
  relire().then((contenu) => {
    if (contenu) worker.postMessage({ type: "index", contenu });
  });
})();
