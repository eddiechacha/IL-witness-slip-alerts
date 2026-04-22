#!/bin/bash
# 1. What categories come back from the Google Sheet loader
echo '=== STC Google Sheet category values ==='
grep -n 'category\|Category\|STC_CAT\|stc_cat\|fetch_stc\|gsheet\|spreadsheet\|normalize' \
  /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py | head -40

echo ''
echo '=== Lines around stc_bills subjects assignment ==='
awk 'NR>=85 && NR<=130' /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py

echo ''
echo '=== Line range around STC stub creation in main() ==='
awk 'NR>=1220 && NR<=1270' /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py

echo ''
echo '=== bills.json writer + docs/data area ==='
awk 'NR>=1450 && NR<=1510' /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py

echo ''
echo '=== docs/data directory contents ==='
ls -la /Users/eddie_chacha/Git/IL-witness-slip-alerts/docs/data/ 2>/dev/null || echo 'not found'

echo ''
echo '=== Existing cache files ==='
find /Users/eddie_chacha/Git/IL-witness-slip-alerts -name '*.json' -o -name '*cache*' 2>/dev/null | grep -v node_modules | grep -v .git

echo ''
echo '=== get_bill_status_url method ==='
grep -n 'get_bill_status_url\|bill_status_url\|ilga.gov/legislation\|ilga.gov/Legislation' \
  /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py | head -20
