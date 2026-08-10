# Catalog site — data-driven from `index.json`

The landing page is **generated entirely from the published `index.json`** — no
hand-maintained module list. For every package the generator reads the manifest
the release action already embedded (`display_name`, `description`, `category`,
`version`, `dependencies`, ed25519 `signer`) and extracts the module icon from
its `.lgx` (a gzipped tar; the icon sits at `variants/<platform>/<icon>`),
inlining everything into a single self-contained `dist/index.html`.

**Add a module to the catalog → it appears here on the next rebuild.** No edits.

## Build locally

```sh
# against the live catalog
python3 site/gen_modules_page.py --index-url "$(jq -r .indexUrl ../logos-repo.json)" --out dist/index.html

# offline against the bundled fixture (placeholder icons, instant)
python3 site/gen_modules_page.py --index site/testdata/sample-index.json --out /tmp/preview.html --offline
```

## Optional editorial layer — `overrides.json`

Everything factual comes from the index. `overrides.json` (keyed by module
name) only supplies what a manifest can't know: `featured`, a `bucket` category
override, a longer `blurb`, or a hand-picked `homepage`. It is merged *over* the
autoloaded data and is entirely optional — delete it and the catalog still
renders.

## Deploy

`.github/workflows/site.yml` fetches the published index, runs the generator
(icons cached by `sha256`), and deploys to GitHub Pages at
**modules.vpavlin.xyz**. It re-runs on site changes, after every *Rebuild
index*, daily, and on demand.
