# cache/

Runtime cache files written by `witness_slip_notifier.py`. All files here
are auto-generated and safe to delete — they will be recreated on the next
run.

## Files

### `stc_tracked_bills.json`
Cached copy of the STC Google Sheet (the list of bills Strong Towns Chicago
is actively tracking). Refreshed every **12 hours**. Falls back to the
hard-coded `STC_TRACKED_BILLS` dict in the script if both the live fetch
and this cache fail.

Schema:
```json
{
  "fetched_at": 1713800000,
  "bills": {
    "HB2454": ["Biking", "Adds bicycles as intended users of roadways", "Proponent"]
  }
}
```

### `ilga_hearings.json`
Cached hearing schedule scraped from ILGA committee pages. Updated every
run. **Past hearings are automatically evicted** on load — only hearings
whose date is >= today are retained. This means a bill that was manually
added to the STC sheet will inherit its hearing from this cache even if
ILGA's site is temporarily unavailable.

Schema:
```json
{
  "updated_at": "2026-04-22T15:30:00",
  "bills": {
    "SB4061": {
      "hearing_date": "2026-04-23T13:30:00",
      "slip_url": "https://ilga.gov/Senate/hearings/details/3072/22865/createwitnessslip"
    }
  }
}
```

## Notes
- Both files are listed in `.gitignore` and should **not** be committed.
- To force a fresh STC sheet fetch, delete `stc_tracked_bills.json` or
  simply wait for the 12-hour TTL to expire.
- To clear stale hearing data, delete `ilga_hearings.json`.
