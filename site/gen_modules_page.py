#!/usr/bin/env python3
"""Generate the vpavlin Logos catalog landing page — fully data-driven.

Two sources, both auto-loaded, no hand-maintained lists:

  * Basecamp **modules** — from the `lgpd` catalog `index.json`, which already
    embeds each version's full manifest (display_name, description, category,
    icon name, version, dependencies, ed25519 signer). Module icons are pulled
    out of each `.lgx` (a gzipped tar; icon at `variants/<plat>/<icon>`).

  * Android **apps** — from an F-Droid repo `index-v2.json` (name, summary,
    description, categories, per-version APK). App icons come from the repo.

Everything is inlined into a single self-contained `dist/index.html`. Add a
module or publish an app → it appears on the next rebuild. No edits.

An optional `overrides.json` (keyed by module/app name or package) supplies the
few purely editorial bits a manifest can't know (featured / bucket / blurb /
homepage), merged over the auto-loaded data.

Usage:
    gen_modules_page.py --index index.json \
        --fdroid-index https://apps.vpavlin.xyz/fdroid/repo/index-v2.json \
        --fdroid-base  https://apps.vpavlin.xyz/fdroid/repo \
        --out dist/index.html
    # local fixtures / offline:
    gen_modules_page.py --index site/testdata/sample-index.json --offline --out /tmp/p.html
"""
import argparse, base64, html, io, json, os, sys, tarfile, urllib.request

CATALOG_TITLE = "vpavlin's Logos"
BASECAMP_REPO_URL = "https://apps.vpavlin.xyz/logos-repo.json"  # paste into Basecamp
BASECAMP_INSTALL_URL = "https://logos.co"      # where to get the Basecamp desktop app
FDROID_INSTALL_URL = "https://f-droid.org"     # where to get the F-Droid client
CACHE_DIR = os.path.expanduser("~/.cache/logos-catalog-icons")

# --------------------------------------------------------------- shared helpers

def _read(path=None, url=None):
    if path:
        with open(path) as f:
            return json.load(f)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def _is_url(s):
    return bool(s) and s.split("://", 1)[0] in ("http", "https")


def data_uri(data, ext):
    mime = {"svg": "image/svg+xml", "png": "image/png", "jpg": "image/jpeg",
            "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "application/octet-stream")
    return f"data:{mime};base64," + base64.b64encode(data).decode()


_PALETTE = ["#2563eb", "#0891b2", "#7c3aed", "#c2410c", "#059669",
            "#db2777", "#4f46e5", "#ca8a04", "#dc2626", "#0d9488"]


def placeholder_icon(key, title):
    """Deterministic lettered monogram when something ships no icon."""
    color = _PALETTE[sum(key.encode()) % len(_PALETTE)]
    letter = html.escape((title or key or "?").strip()[:1].upper())
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">'
        f'<rect width="96" height="96" rx="20" fill="{color}"/>'
        f'<text x="50%" y="52%" dy=".35em" text-anchor="middle" '
        f'font-family="system-ui,sans-serif" font-size="48" font-weight="700" '
        f'fill="#fff">{letter}</text></svg>'
    )
    return data_uri(svg.encode(), "svg")


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def loc(v, default=""):
    """Pick an English-ish value out of an F-Droid localized dict (or pass through)."""
    if isinstance(v, dict):
        for k in ("en-US", "en", *v.keys()):
            if k in v:
                return v[k]
        return default
    return v if v is not None else default


def fdroid_file(v):
    """Resolve an F-Droid file ref to its path. v2 nests it as {locale:{name,sha256,size}}."""
    v = loc(v)
    if isinstance(v, dict):
        return v.get("name", "")
    return v or ""


# --------------------------------------------------------------- module source

def _latest(pkg):
    vs = pkg.get("versions") or []
    return sorted(vs, key=lambda v: v.get("releasedAt", ""), reverse=True)[0] if vs else None


def _fetch_cached(url, key):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, key) if key else None
    if cache and os.path.exists(cache):
        return open(cache, "rb").read()
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    if cache:
        open(cache, "wb").write(data)
    return data


def _icon_from_lgx(lgx_bytes, icon_name):
    try:
        tf = tarfile.open(fileobj=io.BytesIO(lgx_bytes), mode="r:gz")
    except (tarfile.TarError, OSError):
        return None
    with tf:
        want = os.path.basename(icon_name) if icon_name else None
        files = [m for m in tf.getmembers() if m.isfile()]
        cands = [m for m in files if want and os.path.basename(m.name) == want] or \
                [m for m in files if m.name.lower().endswith((".png", ".svg"))]
        cands.sort(key=lambda m: ("icons/" in m.name, m.name.count("/"), len(m.name)))
        for m in cands:
            if m.size > 400_000:
                continue
            ext = "svg" if m.name.lower().endswith(".svg") else "png"
            return tf.extractfile(m).read(), ext
    return None


def build_module_cards(index, overrides, offline):
    cards = []
    for pkg in index.get("packages", []):
        v = _latest(pkg)
        if not v:
            continue
        m = v.get("manifest", {}) or {}
        name = pkg.get("name", m.get("name", "?"))
        ov = overrides.get(name, {})
        title = m.get("display_name") or name
        icon = None
        if not offline:
            try:
                lgx = _fetch_cached(v["url"], (v.get("sha256", "") or "") + ".lgx")
                got = _icon_from_lgx(lgx, m.get("icon"))
                if got:
                    icon = data_uri(*got)
            except Exception as e:
                print(f"  ! module icon {name}: {e}", file=sys.stderr)
        signer = (v.get("signature") or {}).get("signer") or {}
        cards.append({
            "kind": "module", "key": name, "title": title,
            "desc": ov.get("blurb") or m.get("description") or "",
            "category": (ov.get("bucket") or m.get("category") or "Other").strip() or "Other",
            "version": m.get("version") or "", "deps": m.get("dependencies") or [],
            "signer": signer.get("name") or "", "signer_url": signer.get("url") or "",
            "signed": bool(v.get("signature")), "size": v.get("size", 0),
            "url": v.get("url", ""), "install": "lgpd",
            "homepage": ov.get("homepage") or signer.get("url") or "",
            "icon": icon or placeholder_icon(name, title), "featured": bool(ov.get("featured")),
        })
    return cards


# --------------------------------------------------------------- app source (F-Droid)

def build_app_cards(fdroid_index, base_url, repo_dir, overrides, offline):
    """Render Android apps from an F-Droid index-v2.json.

    base_url  — public URL prefix used for APK/icon links on the page.
    repo_dir  — local repo dir (when the index is a local file) to read icons from.
    """
    cards = []
    base = (base_url or "").rstrip("/")
    for pkgname, p in (fdroid_index.get("packages") or {}).items():
        meta = p.get("metadata", {}) or {}
        ov = overrides.get(pkgname, {}) or overrides.get(loc(meta.get("name")), {})
        # newest version (F-Droid keys versions by hash; sort by manifest.versionCode)
        vers = list((p.get("versions") or {}).values())
        vers.sort(key=lambda v: (v.get("manifest", {}) or {}).get("versionCode", 0), reverse=True)
        v = vers[0] if vers else {}
        mani = v.get("manifest", {}) or {}
        apk_rel = (v.get("file", {}) or {}).get("name", "")
        title = loc(meta.get("name"), pkgname)

        icon = None
        icon_ref = fdroid_file(meta.get("icon"))
        if icon_ref:
            try:
                if repo_dir and not _is_url(icon_ref):
                    fp = os.path.join(repo_dir, icon_ref.lstrip("/"))
                    if os.path.exists(fp) and os.path.getsize(fp) < 400_000:
                        icon = data_uri(open(fp, "rb").read(), fp.rsplit(".", 1)[-1].lower())
                elif not offline and base:
                    data = _fetch_cached(base + "/" + icon_ref.lstrip("/"), None)
                    icon = data_uri(data, icon_ref.rsplit(".", 1)[-1].lower())
            except Exception as e:
                print(f"  ! app icon {pkgname}: {e}", file=sys.stderr)

        cards.append({
            "kind": "app", "key": pkgname, "title": title,
            "desc": ov.get("blurb") or loc(meta.get("summary")) or loc(meta.get("description")) or "",
            "category": (ov.get("bucket") or (meta.get("categories") or ["App"])[0]).strip() or "App",
            "version": mani.get("versionName") or "", "deps": [],
            "signer": meta.get("authorName") or "", "signer_url": loc(meta.get("sourceCode")) or "",
            "signed": True, "size": (v.get("file", {}) or {}).get("size", 0),
            "url": (base + apk_rel) if base and apk_rel else "", "install": "apk",
            "homepage": ov.get("homepage") or loc(meta.get("sourceCode")) or "",
            "icon": icon or placeholder_icon(pkgname, title), "featured": bool(ov.get("featured")),
            "package": pkgname,
        })
    cards.sort(key=lambda c: (not c["featured"], c["title"].lower()))
    return cards


# --------------------------------------------------------------- rendering

def render_card(c):
    e = html.escape
    deps = ""
    if c["deps"]:
        chips = "".join(f'<span class="dep">{e(d)}</span>' for d in c["deps"])
        deps = f'<div class="deps">needs {chips}</div>'
    badge = ""
    if c["kind"] == "module" and c["signed"]:
        who = e(c["signer"] or "unknown")
        who = f'<a href="{e(c["signer_url"])}">{who}</a>' if c["signer_url"] else who
        badge = f'<span class="sig" title="ed25519 signed">&#10003; {who}</span>'
    elif c["kind"] == "app" and c["signer"]:
        badge = f'<span class="sig">{e(c["signer"])}</span>'
    meta = " · ".join(x for x in [
        f'v{e(c["version"])}' if c["version"] else "",
        human_size(c["size"]) if c["size"] else "",
    ] if x)
    action = ""
    if c["url"]:
        label = "Get APK" if c["install"] == "apk" else "Package"
        action = f'<a class="get" href="{e(c["url"])}">{label} &darr;</a>'
    title = e(c["title"])
    if c["homepage"]:
        title = f'<a href="{e(c["homepage"])}">{title}</a>'
    return f"""      <article class="card" data-cat="{e(c['category'].lower())}">
        <img class="icon" src="{c['icon']}" alt="" loading="lazy"/>
        <div class="body">
          <h3>{title}<span class="cat">{e(c['category'])}</span></h3>
          <p class="desc">{e(c['desc'])}</p>
          {deps}
          <div class="foot"><span class="meta">{meta}</span>{badge}{action}</div>
        </div>
      </article>"""


def render_grid(cards):
    return "\n".join(render_card(c) for c in cards) or \
        '      <p class="empty">Nothing here yet.</p>'


def render_page(apps, modules, fdroid_repo_url, generated_at):
    e = html.escape
    default = "modules" if modules else "apps"        # Basecamp first
    a_on = "on" if default == "apps" else ""
    m_on = "on" if default == "modules" else ""
    add_repo = ""
    if fdroid_repo_url and apps:
        add_repo = f'<a class="addrepo" href="{e(fdroid_repo_url)}">+ Add F-Droid repo</a>'
    apps_sub = (f'{len(apps)} Android app' + ("s" if len(apps) != 1 else "") +
                (" · add the repo in F-Droid for auto-updates" if fdroid_repo_url
                 else " · download the APK"))
    mods_sub = (f'{len(modules)} Basecamp app' + ("s" if len(modules) != 1 else "") +
                " · install with lgpd or the package manager")

    # install help (native <details>, no JS)
    mods_help = (
        '<details class="help"><summary>How to install</summary><ol>'
        f'<li>Install <a href="{e(BASECAMP_INSTALL_URL)}">Basecamp</a>, the Logos desktop app.</li>'
        f'<li>Open <b>Package Manager &rarr; Add repository</b> and paste '
        f'<code>{e(BASECAMP_REPO_URL)}</code>.</li>'
        '<li>Pick a module from the catalog and click <b>Install</b>.</li>'
        '</ol></details>') if modules else ''
    fp = fdroid_repo_url.split("fingerprint=", 1)[1].split("&")[0] \
        if fdroid_repo_url and "fingerprint=" in fdroid_repo_url else ""
    fbase = fdroid_repo_url.split("?", 1)[0] if fdroid_repo_url else ""
    add_line = ""
    if fdroid_repo_url:
        add_line = ('<li>Tap <b>+ Add F-Droid repo</b> above'
                    + (f' (or add <code>{e(fbase)}</code>, fingerprint <code>{e(fp)}</code>)'
                       if fp else '') + '.</li>')
    apps_help = (
        '<details class="help"><summary>How to install</summary><ol>'
        f'<li>Install the <a href="{e(FDROID_INSTALL_URL)}">F-Droid</a> app.</li>'
        f'{add_line}'
        '<li>Open the app in F-Droid and tap <b>Install</b>.</li>'
        '</ol></details>') if apps else ''
    gen = e(generated_at or "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{e(CATALOG_TITLE)} — Android &amp; Basecamp apps</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --fg:#16181d; --mut:#5b616e; --line:#e4e7ec;
           --accent:#2563eb; --chip:#eef1f5; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme=light]) {{ --bg:#0f1115; --card:#181b21; --fg:#e8eaed;
      --mut:#9aa1ad; --line:#2a2e37; --accent:#6ea8fe; --chip:#232833; }}
  }}
  :root[data-theme=dark] {{ --bg:#0f1115; --card:#181b21; --fg:#e8eaed; --mut:#9aa1ad;
    --line:#2a2e37; --accent:#6ea8fe; --chip:#232833; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
  header {{ padding:44px 24px 4px; max-width:1080px; margin:0 auto; }}
  header h1 {{ margin:0 0 6px; font-size:30px; letter-spacing:-.02em; }}
  header p {{ margin:0; color:var(--mut); }}
  .tabs {{ max-width:1080px; margin:22px auto 0; padding:0 24px; display:flex; gap:4px;
    border-bottom:1px solid var(--line); }}
  .tab {{ background:none; border:0; border-bottom:2px solid transparent; color:var(--mut);
    font:inherit; font-weight:600; padding:10px 14px; cursor:pointer; margin-bottom:-1px; }}
  .tab span {{ font-size:12px; background:var(--chip); color:var(--mut); border-radius:999px;
    padding:1px 8px; margin-left:6px; }}
  .tab.on {{ color:var(--fg); border-bottom-color:var(--accent); }}
  .tab.on span {{ background:var(--accent); color:#fff; }}
  .theme {{ margin-left:auto; align-self:center; background:none; border:0; cursor:pointer;
    font-size:18px; color:var(--mut); padding:6px 8px; line-height:1; }}
  .theme:hover {{ color:var(--fg); }}
  .help {{ margin:12px 24px 0; font-size:13px; color:var(--mut); }}
  .help summary {{ cursor:pointer; color:var(--accent); font-weight:600; width:max-content; }}
  .help ol {{ margin:8px 0 0; padding-left:20px; }}
  .help li {{ margin:3px 0; }}
  .help code {{ background:var(--chip); padding:1px 6px; border-radius:5px; word-break:break-all; }}
  .help a {{ color:var(--accent); }}
  .panel {{ display:none; max-width:1080px; margin:0 auto; }}
  .panel.on {{ display:block; }}
  .ptop {{ display:flex; align-items:center; justify-content:space-between; gap:12px;
    padding:18px 24px 0; color:var(--mut); font-size:13px; flex-wrap:wrap; }}
  .empty {{ padding:26px; color:var(--mut); }}
  main {{ padding:14px 24px 0; display:grid;
    grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:16px; display:flex; gap:14px; }}
  .icon {{ width:56px; height:56px; border-radius:13px; flex:none; object-fit:cover;
    background:var(--chip); }}
  .body {{ min-width:0; flex:1; }}
  .card h3 {{ margin:0 0 4px; font-size:16px; display:flex; align-items:center;
    gap:8px; flex-wrap:wrap; }}
  .card h3 a {{ color:inherit; text-decoration:none; }}
  .card h3 a:hover {{ color:var(--accent); }}
  .cat {{ font-size:11px; font-weight:600; color:var(--mut); background:var(--chip);
    border-radius:6px; padding:2px 7px; text-transform:capitalize; }}
  .desc {{ margin:0 0 8px; color:var(--mut); font-size:13.5px; }}
  .deps {{ font-size:12px; color:var(--mut); margin-bottom:8px; }}
  .dep {{ background:var(--chip); border-radius:5px; padding:1px 6px; margin-left:4px; }}
  .foot {{ display:flex; justify-content:flex-start; align-items:center; gap:10px;
    font-size:12px; color:var(--mut); flex-wrap:wrap; }}
  .sig {{ color:#059669; white-space:nowrap; }}
  .sig a {{ color:inherit; }}
  .get {{ margin-left:auto; color:var(--accent); font-weight:600; text-decoration:none;
    white-space:nowrap; }}
  .addrepo {{ padding:6px 13px; font-size:13px; border:1px solid var(--accent);
    border-radius:999px; color:var(--accent); text-decoration:none; white-space:nowrap; }}
  footer {{ max-width:1080px; margin:0 auto; padding:36px 24px 50px; color:var(--mut);
    font-size:12.5px; }}
  footer code {{ background:var(--chip); padding:1px 6px; border-radius:5px; }}
</style>
<script>(function(){{try{{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}}})();</script>
</head>
<body>
<header>
  <h1>{e(CATALOG_TITLE)}</h1>
  <p>Local-first apps for Android and Basecamp, on Logos.</p>
</header>
<div class="tabs">
  <button class="tab {m_on}" data-panel="modules">Basecamp <span>{len(modules)}</span></button>
  <button class="tab {a_on}" data-panel="apps">Android <span>{len(apps)}</span></button>
  <button class="theme" id="themeToggle" title="Light / dark" aria-label="Toggle theme">&#9680;</button>
</div>
<div class="panel {m_on}" id="panel-modules">
  <div class="ptop"><span class="sub">{mods_sub}</span></div>
  {mods_help}
  <main>
{render_grid(modules)}
  </main>
</div>
<div class="panel {a_on}" id="panel-apps">
  <div class="ptop"><span class="sub">{apps_sub}</span>{add_repo}</div>
  {apps_help}
  <main>
{render_grid(apps)}
  </main>
</div>
<footer>
  Auto-generated{f' · {gen}' if gen else ''}. Android apps come from the F-Droid repo
  index; Basecamp apps from the <code>lgpd</code> catalog <code>index.json</code> — icons,
  versions, descriptions and signers all straight from each published manifest.
</footer>
<script>
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => {{
    document.querySelectorAll('.tab,.panel').forEach(x => x.classList.remove('on'));
    t.classList.add('on');
    document.getElementById('panel-' + t.dataset.panel).classList.add('on');
  }});
  var tg = document.getElementById('themeToggle');
  if (tg) tg.onclick = () => {{
    var cur = document.documentElement.dataset.theme
      || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {{ localStorage.setItem('theme', next); }} catch (e) {{}}
  }};
</script>
</body>
</html>"""


# --------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--index", help="path to a local lgpd index.json")
    src.add_argument("--index-url", help="URL of the published lgpd index.json")
    ap.add_argument("--fdroid-index", help="path or URL of an F-Droid index-v2.json")
    ap.add_argument("--fdroid-base", help="public URL prefix for APK/icon links")
    ap.add_argument("--fdroid-repo-url", help="F-Droid 'add repo' link for the button")
    ap.add_argument("--out", default="dist/index.html")
    ap.add_argument("--overrides")
    ap.add_argument("--offline", action="store_true",
                    help="skip .lgx / remote-icon downloads; placeholder icons")
    args = ap.parse_args()

    overrides = {}
    if args.overrides and os.path.exists(args.overrides):
        overrides = json.load(open(args.overrides))

    index = _read(args.index, args.index_url)
    modules = build_module_cards(index, overrides, args.offline)

    apps = []
    if args.fdroid_index:
        try:
            as_path = None if _is_url(args.fdroid_index) else args.fdroid_index
            fidx = _read(path=as_path, url=(args.fdroid_index if not as_path else None))
            repo_dir = os.path.dirname(os.path.abspath(as_path)) if as_path else None
            apps = build_app_cards(fidx, args.fdroid_base, repo_dir, overrides, args.offline)
        except Exception as ex:
            print(f"  ! F-Droid source failed ({ex}); rendering Basecamp only", file=sys.stderr)

    print(f"building catalog: {len(apps)} apps + {len(modules)} modules"
          f"{' (offline)' if args.offline else ''}", file=sys.stderr)
    page = render_page(apps, modules, args.fdroid_repo_url, index.get("generatedAt", ""))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w").write(page)
    print(f"wrote {args.out} ({len(apps)+len(modules)} cards, {len(page)} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
