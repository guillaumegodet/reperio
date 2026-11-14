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

  // ------------------------------------------------------------------ titre → ISSN (OpenAlex)
  // Suggestions de revues : autocomplétion OpenAlex (titres incomplets acceptés), puis un appel
  // groupé pour récupérer tous les ISSN des revues proposées.
  const OPENALEX = "https://api.openalex.org";
  const RE_ISSN = /^\s*(\d{4})-?(\d{3}[\dXx])\s*$/;
  const champTitre = $("libelle"), liste = $("suggestions");
  let propositions = [], active = -1, minuterie = null, controleur = null;
  const memoire = new Map();

  function fermer() {
    liste.hidden = true;
    champTitre.setAttribute("aria-expanded", "false");
    champTitre.removeAttribute("aria-activedescendant");
    active = -1;
  }

  function afficher(items, message) {
    propositions = items;
    active = -1;
    liste.textContent = "";
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "vide";
      li.textContent = message || "Aucune revue trouvée : saisissez l'ISSN à côté.";
      liste.appendChild(li);
    }
    items.forEach((it, i) => {
      const li = document.createElement("li");
      li.id = "sugg-" + i;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = it.titre;
      const m = document.createElement("span");
      m.className = "m";
      m.textContent = [it.editeur, it.issns.length ? "ISSN " + it.issns.join(", ") : "sans ISSN",
                       it.articles ? it.articles.toLocaleString("fr-FR") + " articles" : ""]
                      .filter(Boolean).join(" · ");
      li.append(t, m);
      li.addEventListener("mousedown", (ev) => { ev.preventDefault(); choisir(i); });
      liste.appendChild(li);
    });
    liste.hidden = false;
    champTitre.setAttribute("aria-expanded", "true");
  }

  function surligner(i) {
    const lis = liste.querySelectorAll("[role=option]");
    if (!lis.length) return;
    active = (i + lis.length) % lis.length;
    lis.forEach((li, j) => li.setAttribute("aria-selected", String(j === active)));
    champTitre.setAttribute("aria-activedescendant", lis[active].id);
    lis[active].scrollIntoView({ block: "nearest" });
  }

  function choisir(i) {
    const it = propositions[i];
    if (!it) return;
    champTitre.value = it.titre;
    if (it.issns.length) $("issn").value = it.issns.join(" ");
    fermer();
    (it.issns.length ? $("annee") : $("issn")).focus();
  }

  async function chercher(q) {
    if (memoire.has(q)) return memoire.get(q);
    if (controleur) controleur.abort();
    controleur = new AbortController();
    const r = await fetch(OPENALEX + "/autocomplete/sources?q=" + encodeURIComponent(q),
                          { signal: controleur.signal });
    if (!r.ok) throw new Error("OpenAlex " + r.status);
    const res = ((await r.json()).results || []).slice(0, 8);
    const ids = res.map((x) => x.id.split("/").pop());
    let issns = {};
    if (ids.length) {
      const d = await fetch(OPENALEX + "/sources?filter=openalex:" + ids.join("|") +
                            "&select=id,issn_l,issn&per-page=" + ids.length, { signal: controleur.signal });
      if (d.ok) {
        for (const x of (await d.json()).results || []) {
          const tous = [x.issn_l].concat(x.issn || []).filter(Boolean);
          issns[x.id] = [...new Set(tous)];
        }
      }
    }
    const items = res.map((x) => ({
      titre: x.display_name, editeur: x.hint || "", articles: x.works_count || 0,
      issns: issns[x.id] || (x.external_id ? [x.external_id] : []),
    }));
    memoire.set(q, items);
    return items;
  }

  champTitre.addEventListener("input", () => {
    clearTimeout(minuterie);
    const q = champTitre.value.trim();
    const m = RE_ISSN.exec(q);
    if (m) {                       // un ISSN tapé dans le titre : il va dans le champ ISSN
      $("issn").value = m[1] + "-" + m[2].toUpperCase();
      champTitre.value = "";
      fermer();
      $("annee").focus();
      return;
    }
    if (q.length < 3) { fermer(); return; }
    minuterie = setTimeout(async () => {
      try {
        const items = await chercher(q);
        if (champTitre.value.trim() === q) afficher(items);
      } catch (e) {
        if (e.name !== "AbortError") afficher([], "Suggestions indisponibles : saisissez l'ISSN à côté.");
      }
    }, 250);
  });
  champTitre.addEventListener("keydown", (ev) => {
    if (liste.hidden) {
      if (ev.key === "ArrowDown" && propositions.length) { afficher(propositions); surligner(0); ev.preventDefault(); }
      return;
    }
    if (ev.key === "ArrowDown") { surligner(active + 1); ev.preventDefault(); }
    else if (ev.key === "ArrowUp") { surligner(active - 1); ev.preventDefault(); }
    else if (ev.key === "Enter" && active >= 0) { choisir(active); ev.preventDefault(); }
    else if (ev.key === "Escape") { fermer(); ev.preventDefault(); }
  });
  champTitre.addEventListener("blur", () => setTimeout(fermer, 100));

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
      erreurFormulaire(mode === "liste" ? "La liste est vide."
        : !$("issn").value.trim() ? (champTitre.value.trim()
          ? "Choisissez la revue dans les suggestions, ou saisissez son ISSN."
          : "Indiquez un titre ou un ISSN.")
        : "Indiquez la ou les années demandées.");
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
