# IL Witness Slip Alerts

Standalone tool that tracks Illinois urbanist bills (Housing, Biking, Safe Streets, Transit, Transportation) and alerts advocates when witness slips open for committee hearings.

**Live site:** https://eddiechacha.github.io/IL-witness-slip-alerts/

Bill data is auto-updated **twice daily** via GitHub Actions, sourced from ILGA.gov and OpenStates via [govbot](https://github.com/chihacknight/govbot).

---

## How it works end-to-end

```
[STC Google Sheet]         [govbot il-legislation repo]
       ↓ (CSV, 12h cache)         ↓ (OpenStates JSON)
       └─────────────────────────┘
                   ↓
          witness_slip_notifier.py
                   ↓
     [ILGA.gov hearing pages] ←─ scrape & cache (cache/ilga_hearings.json)
                   ↓
        witness_slip_notifications.json
                   ↓
    .github/workflows/update-data.yml
                   ↓
           docs/data/bills.json
                   ↓
           docs/index.html  (GitHub Pages → live site)
```

**Step 1 — Bill sources:** The notifier merges two sources:
1. **STC Google Sheet** — bills Strong Towns Chicago is actively tracking (fetched as CSV, 12-hour cache in `cache/stc_tracked_bills.json`, falls back to hard-coded dict).
2. **govbot data directory** — OpenStates JSON files from [govbot-openstates-scrapers/il-legislation](https://github.com/govbot-openstates-scrapers/il-legislation), providing full bill metadata.

**Step 2 — Hearing detection:** The notifier scrapes ILGA committee hearing pages to find which bills have a scheduled committee hearing. Results are cached in `cache/ilga_hearings.json`; past hearings are evicted automatically on every load.

**Step 3 — Output:** Three output files are written:
- `notifications_output.txt` — plain-text email digest
- `notifications_output.html` — HTML email digest
- `witness_slip_notifications.json` — structured data consumed by the workflow

**Step 4 — Deploy:** The GitHub Actions workflow reads `witness_slip_notifications.json`, adds session-status metadata, and writes `docs/data/bills.json`. GitHub Pages serves `docs/index.html` as the live site.

---

## Repo structure

```
IL-witness-slip-alerts/
├── .github/workflows/
│   └── update-data.yml           ← runs twice daily; clones govbot data, runs notifier, writes docs/data/bills.json
├── cache/
│   ├── README.md                 ← describes cache files (auto-generated, do not commit)
│   ├── stc_tracked_bills.json    ← 12h cache of STC Google Sheet (gitignored)
│   └── ilga_hearings.json        ← hearing schedule cache; past hearings auto-evicted (gitignored)
├── docs/
│   ├── index.html                ← frontend (GitHub Pages)
│   └── data/
│       └── bills.json             ← auto-updated twice daily
├── witness_slip_notifier.py      ← main script (scraper + digest builder)
├── .gitignore
└── README.md
```

---

## Setup

### 1. Enable GitHub Pages

Settings → Pages → Source: **main branch, `/docs` folder**.

### 2. (Optional) Add repo secrets for personalized digests

| Secret | Example | Purpose |
|---|---|---|
| `USER_NAME` | `Eddie Chacha` | Appears in digest header |
| `USER_EMAIL` | `eddie@example.com` | Email digest recipient |
| `USER_ORG` | `Strong Towns Chicago` | Appears in digest header |

### 3. First run

Trigger manually: **Actions → Update Witness Slip Data → Run workflow**.
This generates the first `docs/data/bills.json` so the site has data immediately.

---

## Running locally

```bash
# Install dependency
pip install requests

# Sample mode (downloads a handful of bills from GitHub for smoke-testing)
python witness_slip_notifier.py --sample

# Data-dir mode (point at a local clone of il-legislation)
git clone --depth=1 https://github.com/govbot-openstates-scrapers/il-legislation.git /tmp/il-leg
python witness_slip_notifier.py --data-dir /tmp/il-leg

# GitHub Actions mode (writes output files)
python witness_slip_notifier.py --mode github-action --data-dir /tmp/il-leg
```

Output files written in `--mode github-action`:

| File | Description |
|---|---|
| `witness_slip_notifications.json` | Machine-readable bill list consumed by the workflow |
| `notifications_output.txt` | Plain-text email digest |
| `notifications_output.html` | HTML email digest |

---

## Embed on any site

```html
<iframe src="https://eddiechacha.github.io/IL-witness-slip-alerts/"
        width="100%" height="700"
        style="border:none;border-radius:8px">
</iframe>
```

---

## Key concepts

### Bill categories

The UI groups bills into exactly these buckets. Any bill whose STC sheet category does not exactly match is normalized by `_normalize_category_name()` before being assigned:

| Bucket | Keywords that map to it |
|---|---|
| `Housing` | housing |
| `Biking` | bike, bicycl, e-bike, cycling |
| `Transit` | transit, cta, metra, rail, bus, train |
| `Safe Streets` | street, safety, speed, vision zero |
| `Transportation` | transport, parking |
| `Other` | anything else |

### Witness slip vs ILGA page

- **`witness_slip_url`** — only set when a committee hearing date is confirmed. The frontend should show a "File Witness Slip" button only when this field is non-null.
- **`ilga_url`** — always set. Points to the bill’s BillStatus page on ILGA.gov. Always shown as the "ILGA page" link.

### Hearing cache eviction

Each time the script loads `cache/ilga_hearings.json`, it drops any entry whose `hearing_date` is in the past. This prevents stale hearings from appearing on the site after the hearing has already occurred.

---

## Data sources

| Source | What it provides | How accessed |
|---|---|---|
| [govbot il-legislation](https://github.com/govbot-openstates-scrapers/il-legislation) | OpenStates JSON for all IL bills | Git clone in GitHub Actions |
| [STC Google Sheet](https://www.strongtownschicago.org/witness-slips) | STC priority bill list + stance | Published CSV (12h cache) |
| [ILGA.gov](https://ilga.gov) | Committee hearing dates + witness slip URLs | HTML scraping |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A bill is missing from the site | Its STC sheet category doesn’t map to a canonical bucket | Add keywords to `_normalize_category_name()` |
| Stale hearing dates showing | Cache eviction not running | Delete `cache/ilga_hearings.json` |
| STC sheet not updating | Google Sheets URL changed or sheet unpublished | Re-publish the sheet and update `STC_SHEET_CSV_URL` |
| Witness slip button missing | `witness_slip_url` is null (no hearing yet) | Expected — button only appears when a hearing is confirmed |
| `bills.json` empty | govbot clone failed or notifier crashed | Check Actions logs; run `--sample` locally to verify basic function |
