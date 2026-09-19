# WattleFlow monitoring instance — Grafana

The instance is `HLRQ-20` / `FRQ-OPS-20.1`: one `docker compose up` from this directory plus an
untracked `.env` gives a Pushgateway, a Prometheus that scrapes it, and a Grafana provisioned with
the "resource cost per run" dashboard, a panel template library and the wattleflow palette.

## Run

```bash
cp dockers/monitoring/.env.example dockers/monitoring/.env   # then set the three values
docker compose -f dockers/monitoring/docker-compose.yaml up -d
```

| Service | URL | Note |
|---|---|---|
| Grafana | http://localhost:3000 | sign in with the values from `.env`; folder **WattleFlow** → *WattleFlow — resource cost per run* |
| Prometheus | http://localhost:9090 | scrapes the Pushgateway every 15 s, keeps 15 days |
| Pushgateway | http://localhost:9091 | a run pushes once per pass (`DR-WFL-033`) |

All three ports bind to `127.0.0.1`. Without `.env` Compose refuses to start and names the
missing key. No credential and no signing key exists in any tracked file (P-23, `NFRQ-SEC-09`).

## Palette

Source of truth: `grafana/provisioning/branding/wattleflow-theme.json`. Dashboards and templates
cite the role; the hex value changes only in that file.

| Role | Hex | Use |
|---|---|---|
| `background` | `#2d5a54` | panel background, dark theme |
| `primary` / `warning` / `info` | `#e8b924` | accents, key measures, *warning* threshold |
| `secondary` / `success` | `#6ba89e` | *ok* state |
| `error` | `#c74c3c` | *critical* threshold |
| `text` | `#ffffff` | text on the dark background |

Grafana OSS does not load a theme from a file; the roles are applied by the panel templates.

## Thresholds shown on panels

Display only, never a gate (`NFRQ-DEF-02`): *ok* below 60 % of the usual range, *warning*
60–80 %, *critical* above 80 %. Free storage is inverted: *critical* below 20 % free, *warning*
20–50 %. The usual range is read from the process history, not prescribed (`NFRQ-OBS-04`).

## Files

| File | Carries |
|---|---|
| `docker-compose.yaml` | three services, pinned images, loopback ports, `${VAR:?}` for the three Grafana secrets, named volumes |
| `.env.example` | the keys Compose needs, without values |
| `prometheus/prometheus.yml` | scrape of the Pushgateway with `honor_labels`; no alerting rules |
| `grafana/grafana.ini` | branding, anonymous access off, sign-up off, vendor analytics off |
| `grafana/provisioning/datasources/prometheus.yml` | the `Prometheus` datasource, not editable |
| `grafana/provisioning/dashboards/dashboards.yml` | folder **WattleFlow**, reload every 30 s |
| `grafana/provisioning/dashboards/wattleflow.json` | the dashboard: average pass, last pass, history — filtered by `$workflow` |
| `grafana/provisioning/dashboards/wattleflow-templates.json` | library panels: *Stat — Default*, *Stat — Threshold*, *Bar Gauge — Gradient*, *Time Series — Bars* |
| `grafana/provisioning/branding/wattleflow-theme.json` | the palette |

## Adding a panel

1. Edit the dashboard, add a panel (stat, bar gauge or time series).
2. Colour mode: `thresholds` for stat panels, `gradient` with scheme `RdYlGr` for bar gauges,
   `palette-classic` for time series.
3. Threshold steps use the palette roles: `#6ba89e` (ok), `#e8b924` (warning), `#c74c3c` (critical).
4. Save the JSON back into `grafana/provisioning/dashboards/` — the file is the source of truth;
   a change kept only in the UI is lost on the next provisioning reload.

## Beyond a laptop

Publishing a port on another interface, TLS, a reverse proxy, an external database and an
identity provider are each a change to the compose file with a named audience (`NFRQ-SEC-13`);
none is configured here.
