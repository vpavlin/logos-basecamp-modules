#!/usr/bin/env python3
"""Generate the catalog landing page — fully data-driven from index.json.

Unlike a hand-maintained module list, every card here is rendered straight
from the *published* index: `display_name`, `description`, `category`,
`version`, `dependencies` and the ed25519 `signer` all come from the manifest
the release action already embedded in `index.json`. Icons are pulled out of
each package's `.lgx` (a gzipped tar; the icon lives at `variants/<plat>/<icon>`)
and inlined as data URIs, so the output is a single self-contained HTML file.

Add a module to the catalog -> it appears here on the next rebuild. No edits.

An optional `overrides.json` (keyed by package name) supplies the few purely
editorial bits the manifest can't know — `featured`, `bucket`, a longer
`blurb`, or a hand-picked `homepage`. It is *merged over* the autoloaded data,
so it is always optional and never the source of truth for facts.

Usage:
    gen_modules_page.py --index index.json --out dist/index.html
    gen_modules_page.py --index-url https://.../index.json --out dist/index.html
    gen_modules_page.py --index index.json --offline   # skip .lgx, placeholder icons
"""
import argparse, base64, html, io, json, os, re, sys, tarfile, urllib.request

CATALOG_NAME = "Logos Modules"
CACHE_DIR = os.path.expanduser("~/.cache/logos-catalog-icons")

# ---------------------------------------------------------------- data loading

def load_index(path=None, url=None):
    if path:
        with open(path) as f:
            return json.load(f)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def latest_version(pkg):
    """Newest release for a package (index is usually newest-first; be safe)."""
    vs = pkg.get("versions") or []
    if not vs:
        return None
    return sorted(vs, key=lambda v: v.get("releasedAt", ""), reverse=True)[0]


def fetch_lgx(url, sha256):
    """Download a .lgx once, cached by its sha256 so rebuilds are cheap."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{sha256}.lgx") if sha256 else None
    if cache and os.path.exists(cache):
        return open(cache, "rb").read()
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    if cache:
        with open(cache, "wb") as f:
            f.write(data)
    return data


def extract_icon(lgx_bytes, icon_name):
    """Return (bytes, ext) for the module icon inside a .lgx, or None.

    The manifest gives a bare filename; the file sits under variants/<plat>/.
    Prefer a shallow, non-`icons/` match and a reasonably small image.
    """
    try:
        tf = tarfile.open(fileobj=io.BytesIO(lgx_bytes), mode="r:gz")
    except (tarfile.TarError, OSError):
        return None
    with tf:
        want = os.path.basename(icon_name) if icon_name else None
        files = [m for m in tf.getmembers() if m.isfile()]
        named = [m for m in files if want and os.path.basename(m.name) == want]
        anyimg = [m for m in files if m.name.lower().endswith((".png", ".svg"))]
        cands = named or anyimg
        if not cands:
            return None
        # shallowest path first; deprioritise an `icons/` subfolder duplicate
        cands.sort(key=lambda m: ("icons/" in m.name, m.name.count("/"), len(m.name)))
        for m in cands:
            if m.size > 400_000:
                continue
            data = tf.extractfile(m).read()
            ext = "svg" if m.name.lower().endswith(".svg") else "png"
            return data, ext
    return None


def data_uri(data, ext):
    mime = "image/svg+xml" if ext == "svg" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(data).decode()


# palette for category-derived placeholder monograms
_PALETTE = ["#2563eb", "#0891b2", "#7c3aed", "#c2410c", "#059669",
            "#db2777", "#4f46e5", "#ca8a04", "#dc2626", "#0d9488"]


def placeholder_icon(name, title):
    """A deterministic lettered monogram when a module ships no icon."""
    color = _PALETTE[sum(name.encode()) % len(_PALETTE)]
    letter = html.escape((title or name or "?").strip()[:1].upper())
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
        f'<rect width="96" height="96" rx="20" fill="{color}"/>'
        f'<text x="50%" y="52%" dy=".35em" text-anchor="middle" '
        f'font-family="system-ui,sans-serif" font-size="48" font-weight="700" '
        f'fill="#fff">{letter}</text></svg>'
    )
    return data_uri(svg.encode(), "svg")


# ---------------------------------------------------------------- card model

def build_cards(index, overrides, offline):
    cards = []
    for pkg in index.get("packages", []):
        v = latest_version(pkg)
        if not v:
            continue
        m = v.get("manifest", {}) or {}
        name = pkg.get("name", m.get("name", "?"))
        ov = overrides.get(name, {})

        icon = None
        icon_ref = m.get("icon")
        if not offline:
            try:
                lgx = fetch_lgx(v["url"], v.get("sha256", ""))
                got = extract_icon(lgx, icon_ref)
                if got:
                    icon = data_uri(*got)
            except Exception as e:  # network / archive hiccup -> placeholder
                print(f"  ! icon {name}: {e}", file=sys.stderr)
        title = m.get("display_name") or name
        if not icon:
            icon = placeholder_icon(name, title)

        signer = (v.get("signature") or {}).get("signer") or {}
        cards.append({
            "name": name,
            "title": title,
            "desc": ov.get("blurb") or m.get("description") or "",
            "category": (ov.get("bucket") or m.get("category") or "Other").strip() or "Other",
            "version": m.get("version") or v.get("publisherRef", ""),
            "deps": m.get("dependencies") or [],
            "author": m.get("author") or signer.get("name") or "",
            "signer": signer.get("name") or "",
            "signer_url": signer.get("url") or "",
            "signed": bool(v.get("signature")),
            "size": v.get("size", 0),
            "released": (v.get("releasedAt") or "")[:10],
            "url": v.get("url", ""),
            "homepage": ov.get("homepage") or signer.get("url") or "",
            "icon": icon,
            "featured": bool(ov.get("featured")),
        })
    # featured first, then by category, then title
    cards.sort(key=lambda c: (not c["featured"], c["category"].lower(), c["title"].lower()))
    return cards


# ---------------------------------------------------------------- rendering

def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def render_card(c):
    e = html.escape
    deps = ""
    if c["deps"]:
        chips = "".join(f'<span class="dep">{e(d)}</span>' for d in c["deps"])
        deps = f'<div class="deps">needs {chips}</div>'
    sig = ""
    if c["signed"]:
        who = e(c["signer"] or "unknown")
        who = f'<a href="{e(c["signer_url"])}">{who}</a>' if c["signer_url"] else who
        sig = f'<span class="sig" title="ed25519 signed">&#10003; {who}</span>'
    meta = " · ".join(x for x in [
        f'v{e(c["version"])}' if c["version"] else "",
        human_size(c["size"]) if c["size"] else "",
        e(c["released"]),
    ] if x)
    title = e(c["title"])
    if c["homepage"]:
        title = f'<a href="{e(c["homepage"])}">{title}</a>'
    return f"""      <article class="card" data-cat="{e(c['category'].lower())}">
        <img class="icon" src="{c['icon']}" alt="" loading="lazy"/>
        <div class="body">
          <h3>{title}<span class="cat">{e(c['category'])}</span></h3>
          <p class="desc">{e(c['desc'])}</p>
          {deps}
          <div class="foot"><span class="meta">{meta}</span>{sig}</div>
        </div>
      </article>"""


def render_page(index, cards):
    e = html.escape
    name = index.get("repositoryName") or CATALOG_NAME
    cats = sorted({c["category"] for c in cards}, key=str.lower)
    filters = "".join(
        f'<button class="filter" data-cat="{e(c.lower())}">{e(c)}</button>' for c in cats
    )
    body = "\n".join(render_card(c) for c in cards)
    gen = e(index.get("generatedAt", ""))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{e(name)} — Logos module catalog</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --fg:#16181d; --mut:#5b616e; --line:#e4e7ec;
           --accent:#2563eb; --chip:#eef1f5; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme=light]) {{ --bg:#0f1115; --card:#181b21; --fg:#e8eaed;
      --mut:#9aa1ad; --line:#2a2e37; --accent:#6ea8fe; --chip:#232833; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  header {{ padding:40px 24px 8px; max-width:1080px; margin:0 auto; }}
  header h1 {{ margin:0 0 6px; font-size:30px; letter-spacing:-.02em; }}
  header p {{ margin:0; color:var(--mut); }}
  .filters {{ max-width:1080px; margin:16px auto 0; padding:0 24px;
    display:flex; gap:8px; flex-wrap:wrap; }}
  .filter {{ border:1px solid var(--line); background:var(--card); color:var(--mut);
    border-radius:999px; padding:5px 13px; font-size:13px; cursor:pointer; }}
  .filter.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  main {{ max-width:1080px; margin:20px auto 60px; padding:0 24px;
    display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:16px; display:flex; gap:14px; }}
  .icon {{ width:56px; height:56px; border-radius:13px; flex:none; object-fit:cover;
    background:var(--chip); }}
  .body {{ min-width:0; }}
  .card h3 {{ margin:0 0 4px; font-size:16px; display:flex; align-items:center;
    gap:8px; flex-wrap:wrap; }}
  .card h3 a {{ color:inherit; text-decoration:none; }}
  .card h3 a:hover {{ color:var(--accent); }}
  .cat {{ font-size:11px; font-weight:600; color:var(--mut); background:var(--chip);
    border-radius:6px; padding:2px 7px; text-transform:capitalize; }}
  .desc {{ margin:0 0 8px; color:var(--mut); font-size:13.5px; }}
  .deps {{ font-size:12px; color:var(--mut); margin-bottom:8px; }}
  .dep {{ background:var(--chip); border-radius:5px; padding:1px 6px; margin-left:4px; }}
  .foot {{ display:flex; justify-content:space-between; align-items:center; gap:8px;
    font-size:12px; color:var(--mut); }}
  .sig {{ color:#059669; white-space:nowrap; }}
  .sig a {{ color:inherit; }}
  footer {{ max-width:1080px; margin:0 auto; padding:0 24px 50px; color:var(--mut);
    font-size:12.5px; }}
  footer code {{ background:var(--chip); padding:1px 6px; border-radius:5px; }}
</style>
</head>
<body>
<header>
  <h1>{e(name)}</h1>
  <p>{len(cards)} module{'s' if len(cards)!=1 else ''} · a Logos Basecamp catalog you can install with <code>lgpd</code>.</p>
</header>
<div class="filters"><button class="filter on" data-cat="">All</button>{filters}</div>
<main id="grid">
{body}
</main>
<footer>
  Auto-generated from <code>index.json</code>{f' · {gen}' if gen else ''}. Icons, versions,
  descriptions and signers come straight from each module's published manifest.
</footer>
<script>
  const grid = document.getElementById('grid');
  document.querySelectorAll('.filter').forEach(b => b.onclick = () => {{
    document.querySelectorAll('.filter').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    const c = b.dataset.cat;
    grid.querySelectorAll('.card').forEach(card =>
      card.style.display = (!c || card.dataset.cat === c) ? '' : 'none');
  }});
</script>
</body>
</html>"""


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--index", help="path to a local index.json")
    src.add_argument("--index-url", help="URL of the published index.json")
    ap.add_argument("--out", default="dist/index.html", help="output HTML file")
    ap.add_argument("--overrides", help="optional overrides.json (editorial layer)")
    ap.add_argument("--offline", action="store_true",
                    help="skip .lgx downloads; use placeholder icons")
    args = ap.parse_args()

    index = load_index(args.index, args.index_url)
    overrides = {}
    if args.overrides and os.path.exists(args.overrides):
        overrides = json.load(open(args.overrides))

    print(f"building catalog: {len(index.get('packages', []))} packages"
          f"{' (offline)' if args.offline else ''}", file=sys.stderr)
    cards = build_cards(index, overrides, args.offline)
    page = render_page(index, cards)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(page)
    print(f"wrote {args.out} ({len(cards)} cards, {len(page)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
