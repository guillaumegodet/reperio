"""Génère les SVG du logo Repério dans le dossier passé en argument.

Symbole : un repère de carte (localiser) qui contient un rayon de revues (périodiques) ;
le volume cherché, en ambre, est tiré du rayon. Nom : Lato Bold (SIL OFL) vectorisé,
accent du « é » en ambre.
"""
import os, re, sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

OUT = sys.argv[1]
LATO = "/usr/share/fonts/truetype/lato/Lato-Bold.ttf"

CLAIR = dict(pin="#2f5d8a", dos="#fbfaf7", bande="#2f5d8a", ambre="#e3a33b", texte="#1f2328")
SOMBRE = dict(pin="#79a8d8", dos="#16181c", bande="#79a8d8", ambre="#e8ab45", texte="#e6e6e3")


def symbole(c, dx=0, dy=0):
    """Repère 120×120 (pointe en bas), rayon de trois revues."""
    return f"""<g transform="translate({dx} {dy})">
  <path d="M60 116C52 104 18 76 18 48a42 42 0 0 1 84 0c0 28-34 56-42 68z" fill="{c['pin']}"/>
  <rect x="37" y="30" width="11" height="38" rx="1.5" fill="{c['dos']}"/>
  <rect x="37" y="36" width="11" height="2.5" fill="{c['bande']}"/>
  <rect x="37" y="58" width="11" height="2.5" fill="{c['bande']}"/>
  <rect x="51" y="24" width="11" height="44" rx="1.5" fill="{c['dos']}"/>
  <rect x="51" y="30" width="11" height="2.5" fill="{c['bande']}"/>
  <rect x="51" y="58" width="11" height="2.5" fill="{c['bande']}"/>
  <g transform="rotate(16 66 68)">
    <rect x="66" y="30" width="11" height="38" rx="1.5" fill="{c['ambre']}"/>
    <rect x="66" y="36" width="11" height="2.5" fill="{c['bande']}"/>
    <rect x="66" y="58" width="11" height="2.5" fill="{c['bande']}"/>
  </g>
  <rect x="33" y="68" width="56" height="5" rx="2.5" fill="{c['dos']}"/>
</g>"""


def nom(c, x0, base, taille):
    """'Repério' en tracés ; renvoie (svg, largeur)."""
    f = TTFont(LATO)
    gs, cmap, hmtx, glyf = f.getGlyphSet(), f.getBestCmap(), f["hmtx"], f["glyf"]
    k = taille / f["head"].unitsPerEm
    morceaux, x = [], x0

    def tracer(nom_glyphe, ox, couleur):
        pen = SVGPathPen(gs)
        gs[nom_glyphe].draw(TransformPen(pen, (k, 0, 0, -k, ox, base)))
        morceaux.append(f'<path d="{pen.getCommands()}" fill="{couleur}"/>')

    for ch in "Repério":
        g = cmap[ord(ch)]
        if ch == "é":       # composite e + acute : accent en ambre
            for comp in glyf[g].components:
                tracer(comp.glyphName, x + comp.x * k, c["ambre"] if comp.glyphName == "acute" else c["texte"])
        else:
            tracer(g, x, c["texte"])
        x += hmtx[g][0] * k
    return "\n  ".join(morceaux), x - x0


def svg(w, h, corps, titre):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'width="{w:.0f}" height="{h:.0f}" role="img" aria-label="{titre}">\n'
            f"<title>{titre}</title>\n{corps}\n</svg>\n")


def ecrire(nom_fichier, contenu):
    with open(os.path.join(OUT, nom_fichier), "w", encoding="utf-8") as fh:
        fh.write(contenu)


os.makedirs(OUT, exist_ok=True)
ecrire("reperio-symbole.svg", svg(120, 120, symbole(CLAIR), "Repério"))
ecrire("reperio-symbole-sombre.svg", svg(120, 120, symbole(SOMBRE), "Repério"))

for suffixe, c in (("", CLAIR), ("-sombre", SOMBRE)):
    texte, larg = nom(c, 136, 84, 80)
    ecrire(f"reperio-logo{suffixe}.svg",
           svg(136 + larg + 8, 120, symbole(c) + "\n<g>\n  " + texte + "\n</g>", "Repério"))

# Favicon : carré arrondi, sans le repère (illisible à 16 px)
ecrire("favicon.svg", svg(32, 32, """<rect width="32" height="32" rx="7" fill="#2f5d8a"/>
<rect x="7" y="8" width="5" height="15" rx=".8" fill="#fbfaf7"/>
<rect x="13.5" y="6" width="5" height="17" rx=".8" fill="#fbfaf7"/>
<rect x="20" y="8" width="5" height="15" rx=".8" fill="#e3a33b" transform="rotate(16 20 23)"/>
<rect x="5.5" y="23" width="21" height="3" rx="1.5" fill="#fbfaf7"/>""", "Repério"))
print("ok", sorted(os.listdir(OUT)))


# --------------------------------------------------------------------------- logo animé
# Au survol : « Repér io » (repère, bleu) puis « Re pério » (périodique, ambre).
LATO_REG = "/usr/share/fonts/truetype/lato/Lato-Regular.ttf"
GAP = 16          # espace inséré entre les deux parties du nom


def glyphes(police, texte, x0, base, taille):
    """[(caractère, [(nom_composant, d)]), ...], largeur — un tracé par glyphe (accent à part)."""
    f = TTFont(police)
    gs, cmap, hmtx, glyf = f.getGlyphSet(), f.getBestCmap(), f["hmtx"], f["glyf"]
    k = taille / f["head"].unitsPerEm
    res, x = [], x0
    for ch in texte:
        g = cmap[ord(ch)]
        comps = [(c.glyphName, c.x) for c in glyf[g].components] if glyf[g].isComposite() else [(g, 0)]
        parts = []
        for nomc, ox in comps:
            pen = SVGPathPen(gs)
            gs[nomc].draw(TransformPen(pen, (k, 0, 0, -k, x + ox * k, base)))
            parts.append((nomc, pen.getCommands()))
        res.append((ch, parts))
        x += hmtx[g][0] * k
    return res, x - x0


def chemins(liste, accent_cls="accent"):
    out = []
    for ch, parts in liste:
        for nomc, d in parts:
            cls = f' class="{accent_cls}"' if nomc == "acute" else ""
            out.append(f'<path{cls} d="{d}"/>')
    return "".join(out)


X0, BASE, TAILLE = 136, 84, 80
lettres, larg = glyphes(LATO, "Repério", X0, BASE, TAILLE)
f_b = TTFont(LATO); k_b = TAILLE / 2000
def avance(s): return sum(f_b["hmtx"][f_b.getBestCmap()[ord(c)]][0] for c in s) * k_b
x_p = X0 + avance("Re")            # début de « pér »
x_i = X0 + avance("Repér")         # début de « io »
fin = X0 + larg

# légendes en Lato Regular, centrées sous « Repér » (état A) et sous « pério » décalé (état B)
T_LEG = 15
_, l1 = glyphes(LATO_REG, "repère", 0, 0, T_LEG)
_, l2 = glyphes(LATO_REG, "périodique", 0, 0, T_LEG)
leg1, _ = glyphes(LATO_REG, "repère", (X0 + x_i) / 2 - l1 / 2, 116, T_LEG)
leg2, _ = glyphes(LATO_REG, "périodique", (x_p + fin) / 2 + GAP - l2 / 2, 116, T_LEG)

W = fin + GAP + 8
STYLE = """
.reperio{--rp-bleu:#2f5d8a;--rp-papier:#fbfaf7;--rp-ambre:#e3a33b;--rp-ambre-texte:#b06a0b;--rp-texte:#1f2328;--rp-muet:#5f6670;cursor:default}
@media (prefers-color-scheme:dark){.reperio{--rp-bleu:#79a8d8;--rp-papier:#16181c;--rp-ambre:#e8ab45;--rp-ambre-texte:#e8ab45;--rp-texte:#e6e6e3;--rp-muet:#9aa0a8}}
.pin{fill:var(--rp-bleu)} .dos{fill:var(--rp-papier)} .bande{fill:var(--rp-bleu)} .revue{fill:var(--rp-ambre)}
.mot{fill:var(--rp-texte)} .mot .accent{fill:var(--rp-ambre)} .leg{fill:var(--rp-muet);opacity:0}
.re,.per,.io,.leg,.saut,.sortie,.accent{transform-box:view-box}
.reperio:hover .re,.reperio:focus-visible .re,:focus-visible>.reperio .re{animation:c-re 6s ease-in-out infinite}
.reperio:hover .per,.reperio:focus-visible .per,:focus-visible>.reperio .per{animation:c-per 6s ease-in-out infinite,t-per 6s ease-in-out infinite}
.reperio:hover .per .accent,.reperio:focus-visible .per .accent,:focus-visible>.reperio .per .accent{animation:c-acc 6s ease-in-out infinite}
.reperio:hover .io,.reperio:focus-visible .io,:focus-visible>.reperio .io{animation:c-io 6s ease-in-out infinite,t-io 6s ease-in-out infinite}
.reperio:hover .leg1,.reperio:focus-visible .leg1,:focus-visible>.reperio .leg1{animation:o-leg1 6s ease-in-out infinite}
.reperio:hover .leg2,.reperio:focus-visible .leg2,:focus-visible>.reperio .leg2{animation:o-leg2 6s ease-in-out infinite}
.reperio:hover .saut,.reperio:focus-visible .saut,:focus-visible>.reperio .saut{animation:t-saut 6s ease-in-out infinite}
.reperio:hover .sortie,.reperio:focus-visible .sortie,:focus-visible>.reperio .sortie{animation:t-sortie 6s ease-in-out infinite}
/* 0-8 % repos · 15-42 % « Repér io » · 55-85 % « Re pério » · 93-100 % repos */
@keyframes c-re{0%,8%{fill:var(--rp-texte);opacity:1}15%,42%{fill:var(--rp-bleu);opacity:1}55%,85%{fill:var(--rp-texte);opacity:.28}93%,100%{fill:var(--rp-texte);opacity:1}}
@keyframes c-per{0%,8%{fill:var(--rp-texte)}15%,42%{fill:var(--rp-bleu)}55%,85%{fill:var(--rp-ambre-texte)}93%,100%{fill:var(--rp-texte)}}
@keyframes c-acc{0%,8%{fill:var(--rp-ambre)}15%,42%{fill:var(--rp-bleu)}55%,85%{fill:var(--rp-ambre-texte)}93%,100%{fill:var(--rp-ambre)}}
@keyframes c-io{0%,8%{fill:var(--rp-texte);opacity:1}15%,42%{fill:var(--rp-texte);opacity:.28}55%,85%{fill:var(--rp-ambre-texte);opacity:1}93%,100%{fill:var(--rp-texte);opacity:1}}
@keyframes t-per{0%,42%{transform:none}55%,85%{transform:translateX(GAPpx)}93%,100%{transform:none}}
@keyframes t-io{0%,8%{transform:none}15%,85%{transform:translateX(GAPpx)}93%,100%{transform:none}}
@keyframes o-leg1{0%,10%{opacity:0}17%,40%{opacity:1}47%,100%{opacity:0}}
@keyframes o-leg2{0%,50%{opacity:0}57%,83%{opacity:1}90%,100%{opacity:0}}
@keyframes t-saut{0%,10%{transform:none}16%{transform:translateY(-5px)}20%{transform:none}23%{transform:translateY(-2px)}26%,100%{transform:none}}
@keyframes t-sortie{0%,50%{transform:none}57%,83%{transform:translateY(-9px)}90%,100%{transform:none}}
@media (prefers-reduced-motion:reduce){
 .reperio:hover .per,.reperio:hover .io,.reperio:focus-visible .per,.reperio:focus-visible .io{animation-name:c-per,none}
 .reperio:hover .io,.reperio:focus-visible .io{animation-name:c-io,none}
 .reperio:hover .saut,.reperio:hover .sortie,.reperio:focus-visible .saut,.reperio:focus-visible .sortie{animation:none}}
""".replace("GAP", str(GAP))
# déclencheur par script (.joue) : téléphones sans survol, animation au chargement
STYLE = re.sub(r"\.reperio:hover (\.[\w-]+(?: \.[\w-]+)?)([,{])", r".reperio.joue \1,.reperio:hover \1\2", STYLE)

symbole_anime = """<g class="saut">
  <path class="pin" d="M60 116C52 104 18 76 18 48a42 42 0 0 1 84 0c0 28-34 56-42 68z"/>
  <rect class="dos" x="37" y="30" width="11" height="38" rx="1.5"/><rect class="bande" x="37" y="36" width="11" height="2.5"/><rect class="bande" x="37" y="58" width="11" height="2.5"/>
  <rect class="dos" x="51" y="24" width="11" height="44" rx="1.5"/><rect class="bande" x="51" y="30" width="11" height="2.5"/><rect class="bande" x="51" y="58" width="11" height="2.5"/>
  <g transform="rotate(16 66 68)"><g class="sortie">
    <rect class="revue" x="66" y="30" width="11" height="38" rx="1.5"/><rect class="bande" x="66" y="36" width="11" height="2.5"/><rect class="bande" x="66" y="58" width="11" height="2.5"/>
  </g></g>
  <rect class="dos" x="33" y="68" width="56" height="5" rx="2.5"/>
</g>"""

anime = (f'<svg xmlns="http://www.w3.org/2000/svg" class="reperio" viewBox="0 0 {W:.0f} 124" '
         f'width="{W:.0f}" height="124" role="img" aria-label="Repério : repère + périodique">\n'
         f"<title>Repério — repère + périodique</title>\n<style>{STYLE}</style>\n"
         f"{symbole_anime}\n"
         f'<g class="mot"><g class="re">{chemins(lettres[0:2])}</g>'
         f'<g class="per">{chemins(lettres[2:5])}</g><g class="io">{chemins(lettres[5:7])}</g></g>\n'
         f'<g class="leg leg1">{chemins(leg1)}</g><g class="leg leg2">{chemins(leg2)}</g>\n</svg>\n')
ecrire("reperio-logo-anime.svg", anime)
print("animé : largeur", round(W), "x_p", round(x_p), "x_i", round(x_i), "fin", round(fin))
