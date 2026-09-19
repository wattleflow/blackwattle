# WattleFlow Grafana Setup

Grafana konfiguracija za WattleFlow monitoring stack koristi branding boje i template panele dostojne profesionalnog dashboard-a.

## Boje — WattleFlow Palette

| Namjena | HEX | RGB | Uloga |
|---------|-----|-----|-------|
| Pozadina | `#2d5a54` | rgb(45, 90, 84) | Panel backgrounds, dark theme |
| Primarni (žuta) | `#e8b924` | rgb(232, 185, 36) | Alerts, accents, key metrics |
| Sekundarni (zelena) | `#6ba89e` | rgb(107, 168, 158) | Success, OK status |
| Kritično (crveno) | `#c74c3c` | rgb(199, 76, 60) | Errors, critical threshold |
| Tekst | `#ffffff` | rgb(255, 255, 255) | Text on dark background |

### Threshold Logika

- 🟢 **OK** (`#6ba89e`): vrijednost ispod 60% normalnog opsega
- 🟡 **Warning** (`#e8b924`): vrijednost između 60–80%
- 🔴 **Critical** (`#c74c3c`): vrijednost iznad 80% ili kritična kršenja

**Iznimka — Free storage:** inverzna logika (niska vrijednost = kritično)
- 🔴 **Critical**: < 20% slobodno
- 🟡 **Warning**: 20–50% slobodno
- 🟢 **OK**: > 50% slobodno

## Komponente

### 1. Docker Compose (`docker-compose.yaml`)

Grafana servis konfiguriran s:
- **Theme**: `dark` (koristi tamnu pozadinu)
- **Branding**: WattleFlow naziv, subtitle i naslovi
- **Volume**: `grafana/provisioning/` za dashboarde i datasources
- **Config**: `grafana/grafana.ini` za custom konfiguraciju

```yaml
grafana:
  image: grafana/grafana:11.2.0
  environment:
    GF_THEME_DEFAULT: dark
    GF_BRANDING_APP_TITLE: "WattleFlow"
    GF_BRANDING_LOGIN_TITLE: "WattleFlow Monitoring"
    GF_BRANDING_LOGIN_SUBTITLE: "Resource cost analysis per run"
  volumes:
    - ./grafana/provisioning:/etc/grafana/provisioning:ro
    - ./grafana/grafana.ini:/etc/grafana/grafana.ini:ro
```

### 2. Theme Configuration (`grafana/provisioning/branding/wattleflow-theme.json`)

Definiše boje i defaultne postavke panela:
- Primarni: `#e8b924` (žuta za akcente)
- Sekundarni: `#6ba89e` (zelena za success)
- Pozadina: `#2d5a54` (tamna teal)

### 3. Template Library (`grafana/provisioning/dashboards/wattleflow-templates.json`)

Sadrži 4 reusable panel template-a:

#### Stat Panel — Default
- Fiksna žuta boja (`#e8b924`)
- Koristi se za obične KPI-je

#### Stat Panel — Threshold
- Threshold-based coloriranje (zeleno → žuto → crveno)
- Prilagođeno za postotke i postignuća

#### Bar Gauge — Gradient
- RdYlGr gradient (red → yellow → green)
- Prilagođeno za performanse i resurse

#### Time Series — Bars
- Bar chart s legend-om
- Prilagođeno za vremenski pregled prolaza

### 4. Dashboard (`grafana/provisioning/dashboards/wattleflow.json`)

Glavno 3-dijelno dashboard sa 19 panela:

**Sekcija 1: Prosječni prolaz**
- Documents, Duration, Docs/min
- CPU total, utilisation, per document
- Memory: RSS start/end/peak, growth per doc
- Storage and threshold alerts

**Sekcija 2: Vremenski profil**
- Hotspots — exclusive time per operation
- Longest single call
- Failed operations
- Bytes, characters, storage po komponenti

**Sekcija 3: Trendovi kroz vremenske periode**
- Documents i duration po prolazu
- RSS peak po prolazu
- CPU seconds po prolazu

Svi bar gauge paneli koriste:
- WattleFlow gradient boje
- Threshold markere
- Horizontal layout za lakšu čitanju

## Pokretanje

```bash
# Pokreni monitoring stack
docker compose -f examples/monitoring/docker-compose.yaml up -d

# Grafana je dostupna na
http://localhost:3000

# Login
admin / admin (promijeni prije produkcije)

# Dashboard
Folder "WattleFlow" → "WattleFlow — resource cost per run"
```

## Prilagođavanje

### Dodavanje novog panela sa WattleFlow bojama

1. Otvori dashboard za ediranje
2. Dodaj panel
3. Odaberi tip (stat, bargauge, timeseries)
4. U `Field Config` → `Color` odaberi:
   - `Mode: thresholds` za stat panele
   - `Mode: gradient` s `Scheme: RdYlGr` za bar gauge
   - `Mode: palette-classic` za timeseries

5. U `Thresholds` postavi:
   ```json
   {
     "mode": "absolute",
     "steps": [
       { "color": "#6ba89e", "value": null, "label": "OK" },
       { "color": "#e8b924", "value": 75, "label": "Warning" },
       { "color": "#c74c3c", "value": 90, "label": "Critical" }
     ]
   }
   ```

### Prilagođavanje threshold vrijednosti

Threshold-ove možeš prilagoditi temeljem tvojih SLA-eva:
- Otvori panel za ediranje
- Idi u `Field Config` → `Thresholds`
- Promijeni `value` za Warning (obično 60–75%) i Critical (obično 80–95%)

## Reference

- Grafana verzija: 11.2.0
- Schema verzija: 39
- Dark theme: Grafana default dark
- Boje: WattleFlow brand palette
- Threshold logika: FRQ-PTN-18.1 (alerts), NFRQ-OBS-02 (metrics)

---

**Napomena za produkciju:**
- Promijeni `admin` password prije deployinga
- Dodaj `HTTPS` i reverse proxy
- Konfigurira `GF_ROOT_URL` za production domain
- Koristi external database za persistence (ne SQLite)
- Aktivira auth provider (OAuth, LDAP, itd.)
