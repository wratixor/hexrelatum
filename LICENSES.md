# Licensing map

Copyright (c) 2026 Wratixor and Hexrelatum contributors.

This repository intentionally separates software, interface specifications,
and knowledge.

| Paths | License |
|---|---|
| `web/**`, `tools/**`, `tests/**` | GNU AGPL-3.0-or-later |
| `schema/**` | CC0-1.0 |
| `wiki/**`, `lor/wiki/**`, `README.md`, `lor/README.md` | CC BY-SA 4.0 |
| generated `public/index.json`, `public/index.sqlite3`, `lor/public/index.json` and `lor/public/index.sqlite3` | follows the licenses of the indexed content; bundled public content is CC BY-SA 4.0 |
| `provenance.json`, `VERSION`, trivial configuration facts | CC0-1.0 |

The complete license texts are stored in `LICENSE` and `LICENSES/`. SPDX
identifiers may be used in source files where practical.

The software licenses do not automatically apply to independently authored
input data or to output produced from that data. A separately implemented
indexer or connector may use the CC0 index format under its own license,
provided it does not incorporate or form one combined program with AGPL-covered
code. Whether a particular integration is an independent work is a legal and
architectural question; a repository boundary or container alone is not proof.

Credentials, private articles, personal data, wallet records, and confidential
databases must never be committed here and are not offered under these licenses.
