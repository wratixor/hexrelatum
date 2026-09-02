# Hexrelatum

**Hexrelatum** is an open, Git-native wiki that lets every article become the
temporary centre of a three-dimensional map of directly related knowledge.

The source of truth is deliberately small and portable:

- Markdown articles and their six positive coordinates live in `wiki/`;
- `tools/build_index.py` validates the articles and builds a SQLite index plus
  a static JSON representation;
- the dependency-free reader in `web/` displays the selected article and only
  its immediate neighbours;
- code, knowledge, schemas, licenses, and generated public indexes travel in one
  repository.

The name combines *hexa* (six source components) with *relatum* (a thing defined
through relations). The internal **"everything bagel"** reference is an origin
story, not a dependency on somebody else's visual identity.

## Current status

This is the initial `0.2.0-dev` scaffold. It establishes the public repository,
content contract, reference indexer, reproducible fixtures, and a minimal local
reader. The projection and color preview are explicitly versioned as provisional
and are not a final semantic or color-science decision.

Hexrelatum currently has no accounts, server database, subscriptions, votes,
hidden lore, or runtime Git authentication.

Public reader: <https://wratixor.github.io/hexrelatum/>

## Local use

Requires Python 3.11 or newer. Node.js is useful only for the optional JavaScript
syntax check.

```powershell
python tools/build_index.py
python -m http.server 8765
```

Then open `http://127.0.0.1:8765/web/`.

Run all dependency-free checks:

```powershell
python tools/build_index.py --check
python -m unittest discover -s tests -v
python -m compileall -q tools tests
node --check web/app.js
```

## Editing the wiki

Every `*.md` file under `wiki/` begins with a deliberately restricted metadata
header:

```markdown
---
id: example-concept
title: Example concept
coordinates: [2, 5, 1, 4, 3, 3]
home: false
map: false
---
```

Rules:

- `id` is stable and must not change when the title changes;
- `title` is limited to 128 Unicode characters;
- `coordinates` contains exactly six finite numbers, each at least `1`;
- exactly one article has `home: true`;
- `map: true` asks the reader to keep the map as the primary layer;
- relative Markdown links create navigable relationships;
- external links remain ordinary outbound references and are never fetched by
  the indexer.

The three opposed pairs are named in `wiki.config.json`. The bundled general-
knowledge preview uses **Order ↔ Chaos**, **Reality ↔ Fiction**, and
**Concrete ↔ Abstract**. These names and the color preview remain provisional;
forks may define another versioned axis vocabulary without changing reader code.

The main article has no privileged coordinates. Its only special property is
that it opens first, so it should link directly to the important entry points.

## Repository layout

```text
engine contract     schema/
reference indexer   tools/
static reader       web/
all public knowledge wiki/
wiki axis semantics wiki.config.json
generated indexes   public/
validation           tests/ and .github/workflows/
licensing            LICENSE, LICENSES/, LICENSES.md
provenance           provenance.json
```

## Licensing

- engine and indexer code: GNU AGPL-3.0-or-later;
- public index specification: CC0-1.0;
- wiki articles and documentation: CC BY-SA 4.0 unless a file says otherwise.

Generated indexes do not change the license of their source content. See
`LICENSES.md` for the path-by-path boundary.

## Source and provenance

This copy is maintained at
<https://github.com/wratixor/hexrelatum>. The reader exposes repository,
upstream, license, and version links from `provenance.json`. Derived public
deployments should update `repository` to their own public Git repository,
preserve `upstreamRepository`, and provide the source corresponding to the
displayed revision.
