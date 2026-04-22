#!/bin/bash
echo '=== renderBillCard JS (lines 647-704) ==='
awk 'NR>=647 && NR<=720' /Users/eddie_chacha/Git/IL-witness-slip-alerts/docs/index.html
echo ''
echo '=== get_bill_status_url Python ==='
grep -n 'get_bill_status_url\|bill_status_url\|ilga.gov/legislation\|BillStatus\|ilga_url' \
  /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py | head -20
echo ''
echo '=== hearing cache in Python ==='
grep -n 'hearing.*cache\|cache.*hearing\|HEARING_CACHE\|hearing_cache\|cache/hearing' \
  /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py | head -20
echo ''
echo '=== CAT_ORDER and render loops ==='
grep -n 'CAT_ORDER\|for cat in\|Other' \
  /Users/eddie_chacha/Git/IL-witness-slip-alerts/witness_slip_notifier.py | head -20
