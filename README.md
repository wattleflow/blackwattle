# Blackwattle (WattleFlow extension layer)
![WattleFlow Logo](https://raw.githubusercontent.com/wattleflow/core/default/src/wattleflow/logo/wattleflow.png)

[![PyPI version](https://img.shields.io/pypi/v/blackwattle.svg)](https://pypi.org/project/blackwattle/)
[![Python versions](https://img.shields.io/pypi/pyversions/blackwattle.svg)](https://pypi.org/project/blackwattle/)
[![License](https://img.shields.io/pypi/l/blackwattle.svg)](https://github.com/wattleflow/blackwattle/blob/default/LICENSE)

---

*Blackwattle —*
*bridges to many engines,*
*patterns over Apache,*
*opt-in, audit-aware,*
*reference flows that scale.*

---

> ## ⚠ This is not a zero-trust package
>
> `wattleflow` and `wattleflow-workflow` are zero-trust distributions: their transitive
> import closure is the standard library plus each other. **Blackwattle is deliberately
> outside that boundary.** It is the extension layer that reaches third-party subsystems —
> databases, message brokers, OCR engines, NLP models, cloud APIs, radio hardware.
>
> Its components are **reference implementations over existing open-source subsystems**,
> not an audited supply chain. Every optional dependency you install is a supply-chain
> decision, and **auditing it is yours**.
>
> The dependency arrow points one way: `blackwattle → wattleflow-workflow → wattleflow`.
> Neither of the other two depends on blackwattle — the one claim a security reviewer
> needs to check.

| Characteristic | Value |
| --- | --- |
| **Version** | [![PyPI version](https://img.shields.io/pypi/v/blackwattle.svg)](https://pypi.org/project/blackwattle/) |
| **License**              | [![License](https://img.shields.io/pypi/l/wattleflow.svg)](https://github.com/wattleflow/blackwattle/blob/default/LICENSE) |
| **Python Compatibility** | [![Python versions](https://img.shields.io/pypi/pyversions/wattleflow.svg)](https://pypi.org/project/wattleflow/)|
| **Maturity** | Beta — `wattleflow-workflow` is Production/Stable, `wattleflow` is Beta |
| **Required dependencies** | [wattleflow-workflow](https://github.com/wattleflow/workflow) only, which brings [wattleflow](https://github.com/wattleflow/core) transitively |
| **Optional dependencies** | ten named extras plus `all`, none installed by default |
| **Documentation** | [wattleflow/documentation](https://github.com/wattleflow/documentation) |

# What it is

Blackwattle carries the specialisations of the WattleFlow framework for heterogeneous sources
and sinks — connections, drivers, processors, pipelines, documents, strategies, blackboards,
repositories — plus the compliance layer (OSCAL). It builds on the interfaces in `wattleflow`
and the generic implementations in `wattleflow-workflow`.

# New in 0.0.8 — a run you can watch

A pass has always measured itself: the audit log is observed, resources are sampled while the
work runs, and a report closes the pass. What was missing was somewhere to look. This release
adds the monitoring instance — measurement leaves the process as Prometheus exposition, is
pushed once per pass to a Pushgateway, and lands on a Grafana dashboard that ships provisioned,
palette and panel library included.

```bash
cp dockers/monitoring/.env.example dockers/monitoring/.env   # then set the three values
docker compose -f dockers/monitoring/docker-compose.yaml up -d
```

Grafana on `http://localhost:3000`, folder **WattleFlow**, dashboard *resource cost per run*.
No dashboard to build, no datasource to wire, no panel to import.

![Resource cost per run — overview](https://raw.githubusercontent.com/wattleflow/documentation/default/images/grafana/grafana-overview.png)

*Overview — documents, duration, CPU seconds and peak memory of the last pass, per workflow.*

![Where the time goes](https://raw.githubusercontent.com/wattleflow/documentation/default/images/grafana/grafana-run-detail.png)

*Detail — exclusive time per operation, cycles, and bytes and characters per component: the
hotspot is read off the panel, not guessed from a log.*

![Across runs](https://raw.githubusercontent.com/wattleflow/documentation/default/images/grafana/grafana-history.png)

*History — one bar per push, so the cost of a change to a pipeline is visible as the change
lands, not a fortnight later.*

What the instance is careful about:

- **Thresholds are shown, never enforced.** Colour on a panel is a diagnostic reading, not a
  gate; the usual range is read from the process history rather than prescribed.
- **Nothing in this repository holds a credential.** Compose reads the three Grafana secrets
  from an untracked `.env` and refuses to start without them, naming the missing key.
- **Ports bind to `127.0.0.1`.** Publishing on another interface, TLS, a reverse proxy, an
  external database and an identity provider are each a deliberate change with a named
  audience — none is configured here.
- **The provisioned files are the source of truth.** A panel kept only in the Grafana UI is
  lost on the next provisioning reload; the dashboard JSON lives in the repository.

Setup, palette roles and how to add a panel: [`dockers/monitoring/GRAFANA-SETUP.md`](dockers/monitoring/GRAFANA-SETUP.md). The screenshots above live in the documentation repository, under
[`images/grafana`](https://github.com/wattleflow/documentation/tree/default/images/grafana).

# Installation

A bare install pulls only `wattleflow-workflow` and, through it, `wattleflow`:

```bash
pip install blackwattle
```

Every third-party integration is opt-in by extra:

```bash
pip install "blackwattle[documents]"
```

A specialisation imports its third-party library at call time, so a module whose extra is
missing fails where it is used, not on import of the package.

> `pip install wattleflow-workflow[blackwattle]` — the installation contract recorded in
> `DR-PRC-002` — does **not** work: `wattleflow-workflow` declares no such extra. Use the
> direct form above.

## Extras

| Extra | Brings | Notes |
| --- | --- | --- |
| `security` | cryptography | connection and credential handling |
| `sql` | psycopg2-binary, SQLAlchemy | see the psycopg2-binary caveat in `pyproject.toml` |
| `search` | elasticsearch, opensearch-py, pysolr | |
| `streaming` | kafka-python-ng, pyspark, pyarrow | pyspark needs a JVM |
| `cloud` | boto3, paramiko, requests, requests-kerberos, requests-ntlm, websockets | Kerberos/NTLM need system GSSAPI/krb5 headers |
| `data` | pandas, fastavro, rdflib, pyarrow | |
| `documents` | python-docx, pypdf, pdfminer.six, PyMuPDF, Pillow, pytesseract, tika, extract-msg | **licence warning below**; pytesseract needs the `tesseract` binary, tika a JVM |
| `nlp` | spacy, stanza, flair, gliner, transformers, torch, wordfreq | multi-gigabyte; several download models at runtime |
| `media` | anthropic, youtube-transcript-api, yt-dlp | |
| `sdr` | pyrtlsdr[lib], pyrtlsdrlib, numpy | **licence warning below**; needs an RTL2832U receiver on USB |
| `all` | everything **except** `nlp` and `sdr` | breadth without a model runtime or a radio |

> **Licence — `documents`.** PyMuPDF is AGPL-3.0 (or commercial). It is optional and not
> vendored, so the Apache-2.0 terms of this distribution stand — but an install with this
> extra that you redistribute carries AGPL obligations.

> **Licence — `sdr`.** pyrtlsdr is GPL-3.0-or-later and the native librtlsdr it loads is
> GPL-2.0-or-later; the same reasoning applies. The `lib` extra brings a prebuilt librtlsdr
> that its own SBOM does not list — know that before you install it.

## Radio capture (`sdr`)

```bash
pip install "blackwattle[sdr]"
```

One receiver is one connection: claimed exclusively, addressed by a selector that must resolve
to exactly one unit, every parameter read back from the device. A model is a configuration
profile verified against what the device reports, not a class. Verified on a Nooelec NESDR
SMArt v5 (RTL2832U + R820T). Losses are not measurable through this library's synchronous
read, so they are reported as unmeasured, never as zero.

# Supporting services

Container instances a run pushes to or reads from live under `dockers/<instance>/`; the first
is the monitoring stack described above (`dockers/monitoring`: Pushgateway, Prometheus,
Grafana). Secrets come from an untracked `.env` — nothing in this repository holds a
credential.

# Licence

Apache-2.0 — see [LICENSE](LICENSE).
