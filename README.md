# IL Witness Slip Alerts

Standalone tool tracking Illinois urbanist bills (Housing, Biking, Safe Streets, Transit) and alerting advocates when witness slips open for committee hearings.

**Live site:** https://eddiechacha.github.io/IL-witness-slip-alerts/

Data is auto-updated daily via GitHub Actions, sourced from ILGA.gov and OpenStates via [govbot](https://github.com/chihacknight/govbot).

## Embed (for STC or any site)

```html
<iframe src="https://eddiechacha.github.io/IL-witness-slip-alerts/"
        width="100%" height="700"
        style="border:none;border-radius:8px">
</iframe>
```

## Repo structure

```
IL-witness-slip-alerts/
├── .github/workflows/update-data.yml   ← runs daily, writes docs/data/bills.json
├── docs/
│   ├── index.html                       ← the frontend (served via GitHub Pages)
│   └── data/bills.json                  ← auto-updated by the Action
├── witness_slip_notifier.py             ← scraper/notifier script
└── README.md
```

## Setup

1. Enable GitHub Pages → **Settings → Pages → Source: `main` branch, `/docs` folder**
2. (Optional) Add repo secrets for personalized digests:
   - `USER_NAME` — your name
   - `USER_EMAIL` — your email
   - `USER_ORG` — your organization (e.g. "Strong Towns Chicago")
3. Trigger the workflow manually once via **Actions → Update Witness Slip Data → Run workflow** to generate the first `bills.json`

## Data source

Bill data comes from [govbot-openstates-scrapers/il-legislation](https://github.com/govbot-openstates-scrapers/il-legislation) (public OpenStates data). The notifier script cross-references ILGA.gov's hearing calendar to flag bills with upcoming committee hearings.
