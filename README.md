# Blackwattle (WattleFlow Extension Layer)
![WattleFlow Logo](https://raw.githubusercontent.com/wattleflow/core/default/src/wattleflow/logo/wattleflow.png)

[![PyPI version](https://img.shields.io/pypi/v/blackwattle.svg)](https://pypi.org/project/blackwattle/)
[![Python versions](https://img.shields.io/pypi/pyversions/blackwattle.svg)](https://pypi.org/project/blackwattle/)
[![License](https://img.shields.io/pypi/l/blackwattle.svg)](https://github.com/wattleflow/blackwattle/blob/default/LICENSE)

---
Blackwattle —
bridges to many engines,
patterns over Apache,
opt-in, audit-aware,
reference flows that scale.
---

> ## ⚠ This is not a zero-trust package
>
> `wattleflow` and `wattleflow-workflow` are zero-trust distributions: their
> transitive import closure is the standard library plus each other. **Blackwattle
> is deliberately outside that boundary.** It is the extension layer, and it exists
> to reach third-party subsystems — databases, message brokers, OCR engines, NLP
> models, cloud APIs.
>
> The components shipped here are **reference implementations over existing
> open-source subsystems**, not audited software supply chain. Every optional
> dependency you install is a supply-chain decision, and **auditing it is yours**.
>
> The dependency arrow points one way only: `blackwattle → wattleflow-workflow →
> wattleflow`. Neither of the other two has blackwattle in its dependency graph,
> which is the one claim a security reviewer needs to check.

| Characteristic | Value |
| --- | --- |
| **Version** | [![PyPI version](https://img.shields.io/pypi/v/blackwattle.svg)](https://pypi.org/project/blackwattle/) (latest release) |
| **License** | [![License](https://img.shields.io/pypi/l/blackwattle.svg)](https://github.com/wattleflow/blackwattle/blob/default/LICENSE) |
| **Python Compatibility** | [![Python versions](https://img.shields.io/pypi/pyversions/blackwattle.svg)](https://pypi.org/project/blackwattle/) |
| **Maturity** | Beta — deliberately below the Production/Stable carried by core and workflow |
| **Required dependencies** | [wattleflow-workflow](https://www.github.com/wattleflow/workflow.git) only, which brings [wattleflow](https://www.github.com/wattleflow/core.git) transitively |
| **Optional dependencies** | Ten named extras, none installed by default — see below |
| **Documentation** | [Wattleflow **Documentation**](https://github.com/wattleflow/documentation.git) |

# Blackwattle

Blackwattle is the extension layer of the WattleFlow framework: it carries the
specializations for heterogeneous sources and sinks — connections, drivers,
processors, pipelines, documents, strategies, blackboards — plus the compliance
layer, built on the design patterns defined in `wattleflow` and the generic
implementations in `wattleflow-workflow`.

Its modular, horizontally scalable architecture integrates pipelines to and from
heterogeneous subsystems, enabling flexible and efficient workflow orchestration.

# Installation

A bare install pulls **nothing unvetted** — only `wattleflow-workflow` and, through
it, `wattleflow`. Every third-party integration is opt-in by name:

```bash
pip install blackwattle
```

Each specialization lazy-loads its third-party library at call time, so a module
whose extra is not installed fails where it is used, not on import of the package.

> **`pip install wattleflow-workflow[blackwattle]` does not work yet.** That is the
> documented installation contract (`DR-PRC-002` §Ugovor), but the `[blackwattle]`
> extra has not been declared in `wattleflow-workflow` — it is an aspiration, not a
> working command. Use the direct form above until the extra exists.

## Optional dependency groups

```bash
pip install "blackwattle[sql,documents]"
```

| Extra | Brings | Notes |
| --- | --- | --- |
| `security` | cryptography | Connection and credential handling |
| `sql` | psycopg2-binary, SQLAlchemy | See the psycopg2-binary caveat in `pyproject.toml` |
| `search` | elasticsearch, opensearch-py, pysolr | |
| `streaming` | kafka-python-ng, pyspark, pyarrow | **pyspark needs a JVM** |
| `cloud` | boto3, paramiko, requests, requests-kerberos, requests-ntlm, websockets | Kerberos/NTLM need system GSSAPI/krb5 headers |
| `data` | pandas, fastavro, rdflib, pyarrow | |
| `documents` | python-docx, pypdf, pdfminer.six, PyMuPDF, Pillow, pytesseract, tika, extract-msg | **See the licence warning below.** pytesseract needs the `tesseract` binary; tika needs a JVM |
| `nlp` | spacy, stanza, flair, gliner, transformers, torch, wordfreq | Multi-gigabyte; several need runtime model downloads pip does not manage |
| `media` | anthropic, youtube-transcript-api, yt-dlp | |
| `all` | everything **except** `nlp` | Breadth without a model runtime |

> **Licence warning — `documents`.** PyMuPDF is AGPL-3.0 (or commercial). It is an
> optional dependency and not vendored, so it does not change the Apache-2.0 terms
> of this distribution — but if you install this extra and redistribute the result,
> you inherit AGPL obligations. Decide that deliberately.

# Key Features

| Key Feature | Characteristic |
| --- | --- |
| Modular Architecture | Designed for extensibility and maintainability. |
| Code Reusability | Facilitates development by encouraging the reuse of framework components. |
| Explicit Trust Boundary | The unvetted surface is isolated in this package and opt-in per extra, so the framework core stays auditable. |
| Scalable and Clear | Suitable for both small and enterprise-level workflow orchestration. |

# Documentation
Comprehensive documentation will be available at the [Git Hub](https://github.com/wattleflow/documentation.git).

# Contributing
We welcome contributions! Please check our GitHub repository for guidelines.

# License
Blackwattle is licensed under the Apache 2.0 License.
See the LICENSE file for more details.
