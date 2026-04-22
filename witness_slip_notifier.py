#!/usr/bin/env python3
"""
IL Witness Slip Notifier - Urbanist Focus
  Topics: Housing, Transportation, Biking, Safe Streets, Transit, and more
Privacy-first: No config files, uses environment variables only.

Two input modes:
  --feed <path>      Read the RSS feed produced by `govbot build` (preferred).
                     Bills are already tagged by govbot; this script finds the
                     ones with upcoming committee hearings, resolves witness
                     slip URLs, and builds the activist email digest.
  --data-dir <path>  Legacy mode: parse raw OpenStates JSON directly.
  --sample           Download a small sample from GitHub for local testing.
"""

import json
import os
import sys
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from enum import Enum
from pathlib import Path
import argparse
import requests
import tempfile
import smtplib
from email.message import EmailMessage




# Strong Towns Chicago tracked bills — 104th General Assembly
# Always included in digest regardless of govbot keyword tagging.
# Format: normalized_bill_number -> (category, plain_description, stance)
STC_TRACKED_BILLS = {
    "HB5626": ("Housing",      "BUILD Act (Omnibus) — House omnibus housing bill",                 "Proponent"),
    "SB4061": ("Housing",      "BUILD Act — Single stair reform",                                 "Proponent"),
    "SB4064": ("Housing",      "BUILD Act — Parking reform (caps minimums)",                     "Proponent"),
    "SB4062": ("Housing",      "BUILD Act — Impact fee modernization",                            "Proponent"),
    "SB4060": ("Housing",      "BUILD Act — 2–8 units by right (missing middle)",                 "Proponent"),
    "SB4071": ("Housing",      "BUILD Act — Legalizes ADUs statewide",                           "Proponent"),
    "SB4063": ("Housing",      "BUILD Act — Third-party review for housing permits",              "Proponent"),
    "HB5083": ("Housing",      "YIGBY — Faith-based housing & mixed-use by-right",               "Proponent"),
    "SB3187": ("Housing",      "YIGBY — Faith-based housing & mixed-use by-right",               "Proponent"),
    "HB4835": ("Housing",      "Adaptive reuse of commercial buildings",                         "Proponent"),
    "HB5198": ("Housing",      "AHPAA Improvement Act",                                          "Proponent"),
    "SB3478": ("Biking",       "Bike grid enabling legislation",                                 "Proponent"),
    "HB2454": ("Biking",       "Adds bicycles as intended users of roadways",                   "Proponent"),
    "HB4660": ("Biking",       "Idaho Stop — legalizes yield-at-stop for cyclists",              "Proponent"),
    "HB4925": ("Biking",       "Class 3 e-bike: 18+ to carry passenger under 18",               "Proponent"),
    "HB2934": ("Safe Streets", "Lowers urban speed limit 30→20 mph / alley 15→10 mph",           "Proponent"),
    "HB4281": ("Safe Streets", "Speed cameras in Cook County cities 25k+ population",           "Proponent"),
    "HB4333": ("Safe Streets", "Lowers DUI BAC threshold 0.08% → 0.05%",                        "Proponent"),
    "HB4759": ("Transit",      "Green Light for Buses — transit signal priority",               "Proponent"),
    "SB3627": ("Safe Streets", "Quick Build — IDOT must accept quick-build safety infra",       "Proponent"),
    "HB5081": ("Safe Streets", "REMOVES safety zones when speed limit lowered to 20 mph",       "Opponent"),
}


class BillReading(Enum):
    FIRST = "First Reading"
    SECOND = "Second Reading"
    THIRD = "Third Reading"


class Chamber(Enum):
    HOUSE = "House"
    SENATE = "Senate"


class Bill:
    """Illinois state bill with topic filtering"""
    
    def __init__(self, bill_number: str, chamber: Chamber, title: str,
                 sponsor: str, next_reading: BillReading,
                 subjects: List[str] = None,
                 committee_hearing_date: Optional[datetime] = None,
                 committee_name: Optional[str] = None,
                 ilga_url: Optional[str] = None):
        self.bill_number = bill_number
        self.chamber = chamber
        self.title = title
        self.sponsor = sponsor
        self.next_reading = next_reading
        self.subjects = subjects or []
        self.committee_hearing_date = committee_hearing_date
        self.committee_name = committee_name
        self.ilga_url = ilga_url or self.get_bill_status_url()
    
    def matches_topics(self, topic_list: List[str]) -> bool:
        """Case-insensitive partial matching"""
        if not self.subjects:
            return False
        
        normalized_subjects = [s.lower() for s in self.subjects]
        normalized_topics = [t.lower().strip() for t in topic_list]
        
        for subject in normalized_subjects:
            for topic in normalized_topics:
                if topic in subject or subject in topic:
                    return True
        return False
    
    def get_witness_slip_url(self) -> str:
        """Return the most specific witness slip URL available.

        Priority:
          1. ilga_url from OpenStates sources (already points to the ILGA
             BillStatus page which has a 'Witness Slips' tab).
          2. Constructed BillStatus URL with #tab=witnessSlips anchor.
          3. Generic chamber hearings page as a last resort.
        """
        if self.ilga_url and "ilga.gov" in self.ilga_url:
            # Append the Witness Slips tab anchor if not already there
            if "#" not in self.ilga_url:
                return f"{self.ilga_url}#tab=witnessSlips"
            return self.ilga_url
        # Fallback: constructed BillStatus URL
        bill_status = self.get_bill_status_url()
        if bill_status:
            return f"{bill_status}#tab=witnessSlips"
        # Last resort: chamber hearings landing page
        chamber_path = self.chamber.value.lower()
        return f"https://ilga.gov/{chamber_path}/hearings"

    def get_bill_status_url(self) -> str:
        doc_type = "HB" if self.chamber == Chamber.HOUSE else "SB"
        bill_num = self.bill_number.replace("HB", "").replace("SB", "").strip()
        return f"https://www.ilga.gov/legislation/BillStatus.asp?DocTypeID={doc_type}&DocNum={bill_num}&GAID=18&SessionID=114"


class GovbotFeedParser:
    """Parse the RSS feed produced by `govbot build`.

    govbot emits a standard RSS 2.0 feed where each <item> represents one
    bill action log entry.  The tags applied by `govbot tag` are stored in
    <category> elements, and the ILGA BillStatus URL lives in <link>.

    We rebuild a minimal Bill object from each item so the rest of the
    notifier pipeline (hearing detection, witness slip URL resolution,
    email generation) is unchanged.
    """

    # RSS namespace govbot uses for extensions
    _NS = {
        'content': 'http://purl.org/rss/1.0/modules/content/',
        'dc':      'http://purl.org/dc/elements/1.1/',
        'atom':    'http://www.w3.org/2005/Atom',
    }

    @classmethod
    def parse_feed(cls, feed_path: str) -> List["Bill"]:
        """Return a deduplicated list of Bill objects from the govbot RSS feed."""
        path = Path(feed_path)
        if not path.exists():
            print(f"❌ Feed file not found: {feed_path}")
            return []

        print(f"📡 Parsing govbot RSS feed: {feed_path}")
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            print(f"❌ Could not parse feed XML: {exc}")
            return []

        root = tree.getroot()
        channel = root.find('channel')
        if channel is None:
            print("❌ No <channel> element in feed.")
            return []

        items = channel.findall('item')
        print(f"📄 Found {len(items)} feed items")

        # Debug: print first item's raw fields so we can see real GUID format
        if items:
            def _t(el, tag):
                e = el.find(tag); return e.text.strip() if e is not None and e.text else ''
            sample = items[0]
            print(f"  [debug] title:  {_t(sample,'title')[:80]}")
            print(f"  [debug] guid:   {_t(sample,'guid')[:120]}")
            print(f"  [debug] link:   {_t(sample,'link')[:120]}")
            cats = [c.text.strip() for c in sample.findall('category') if c.text]
            print(f"  [debug] cats:   {cats}")

        # Deduplicate by bill identifier — one Bill object per bill.
        seen: dict[str, "Bill"] = {}

        for item in items:
            bill = cls._item_to_bill(item)
            if bill is None:
                continue
            if bill.bill_number not in seen:
                seen[bill.bill_number] = bill
            else:
                # Merge: keep the earliest upcoming hearing date
                existing = seen[bill.bill_number]
                if (bill.committee_hearing_date and
                        (existing.committee_hearing_date is None or
                         bill.committee_hearing_date < existing.committee_hearing_date)):
                    existing.committee_hearing_date = bill.committee_hearing_date
                    existing.committee_name = bill.committee_name
                # Merge subjects / govbot tags
                for s in bill.subjects:
                    if s not in existing.subjects:
                        existing.subjects.append(s)

        bills = list(seen.values())
        print(f"✅ Parsed {len(bills)} unique bills from feed")
        return bills

    @classmethod
    def _item_to_bill(cls, item: ET.Element) -> Optional["Bill"]:
        """Convert a single RSS <item> to a Bill, or None if unparseable.

        Feed format (from govbot build):
          <title>Tag1, Tag2 - repo - BILL TITLE</title>
          <link>https://example.com/.../bills/HB1234/metadata.json</link>
          <description><![CDATA[
            id: HB1234
            log:
              action:
                description: Some action text
                date: 2025-05-31
            bill:
              identifier: HB1234
              title: ACTUAL BILL TITLE
              abstract: ...
          ]]></description>
          <category>Biking</category>
          <guid>repo/.../bills/HB1234/logs/...json</guid>
        """
        import re

        def text(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        title_raw   = text('title')
        guid        = text('guid')
        description = text('description')
        # note: link is example.com placeholder in govbot feed — ignore it

        # ── Extract bill identifier ──────────────────────────────────────
        # govbot GUID format:
        #   il-legislation/country:us/state:il/sessions/104th/bills/HB2270/logs/...
        #   il-legislation/country:us/state:il/sessions/104th/bills/AM1030415/logs/...
        #
        # For HB/SB bills: use the GUID path segment directly.
        # For AM (amendment) bills: fall back to the title which contains the
        # underlying bill number as "HB NNNN" or "SB NNNN".
        # Title format: "Tag1, Tag2 - repo - BILL-TYPE IDENTIFIER: TITLE"
        #   e.g. "Housing, Transportation - il-legislation - APPOINT-ASHISH SHARMA"
        #   e.g. "Biking - il-legislation - HB 2454: BICYCLES-ROADWAYS"

        BILL_RE   = re.compile(r'\b([HS][BCR]\d+)\b', re.I)   # HB/SB/HR/SR
        AM_RE     = re.compile(r'\bAM(\d+)\b', re.I)           # amendment IDs
        GUID_BILL = re.compile(r'/bills/([A-Z]{2,3}\d+)/', re.I) # anything in /bills/.../

        bill_id = None

        # 1. Prefer standard bill IDs from GUID path
        gm = GUID_BILL.search(guid)
        if gm:
            raw = gm.group(1).upper()
            if BILL_RE.match(raw):
                bill_id = raw
            # If it's an AM id, try extracting HB/SB from title
            elif AM_RE.match(raw):
                tm2 = BILL_RE.search(title_raw)
                if tm2:
                    bill_id = tm2.group(1).upper()

        # 2. Fallback: scan title for HB/SB pattern
        if not bill_id:
            tm2 = BILL_RE.search(title_raw)
            if tm2:
                bill_id = tm2.group(1).upper()

        if not bill_id:
            # Skip silently — AM appointments, proclamations, etc.
            return None

        # ── Build ILGA URL from GUID (never trust the example.com link) ──
        num_only  = re.sub(r'[^\d]', '', bill_id)
        doc_type  = 'HB' if bill_id.startswith('H') else 'SB'
        ilga_base = (
            f"https://www.ilga.gov/legislation/BillStatus.asp"
            f"?DocTypeID={doc_type}&DocNum={num_only}&GAID=18&SessionID=114"
        )

        categories  = [c.text.strip() for c in item.findall('category') if c.text]
        chamber     = Chamber.HOUSE if bill_id.startswith('H') else Chamber.SENATE

        bill_title = action_desc = action_date_str = ''
        if description:
            tm  = re.search(r'\btitle:\s*(.+)$',       description, re.M)
            acm = re.search(r'\bdescription:\s*(.+)$', description, re.M)
            if tm:  bill_title  = tm.group(1).strip()
            if acm: action_desc = acm.group(1).strip()

        if not bill_title:
            parts = title_raw.split(' - ')
            bill_title = parts[-1].strip() if parts else title_raw

        committee_name = None
        if action_desc:
            cm = re.search(
                r'(?:assigned to|referred to|re-referred to)\s+(.+?)(?:\s+committee)?$',
                action_desc, re.I)
            if cm:
                committee_name = cm.group(1).strip()

        ad = action_desc.lower()
        reading = (BillReading.THIRD if 'third reading' in ad
                   else BillReading.SECOND if 'second reading' in ad
                   else BillReading.FIRST)

        return Bill(
            bill_number=bill_id, chamber=chamber, title=bill_title,
            sponsor='Unknown', next_reading=reading, subjects=categories,
            committee_hearing_date=None, committee_name=committee_name,
            ilga_url=ilga_base,
        )


class OpenStatesParser:
    """Parse OpenStates IL data directly"""
    
    @staticmethod
    def parse_data_directory(data_dir: str) -> List[Bill]:
        print(f"📂 Parsing OpenStates data from: {data_dir}")
        data_path = Path(data_dir)

        if not data_path.exists():
            print(f"❌ Data directory not found: {data_dir}")
            return []

        # govbot-openstates-scrapers layout: flat bill_<uuid>.json files
        # Legacy govbot layout: subdirectories each containing metadata.json
        flat_files = list(data_path.glob("bill_*.json"))
        nested_files = list(data_path.glob("*/metadata.json"))
        bill_files = flat_files if flat_files else nested_files
        flat_mode = bool(flat_files)

        bills = []

        print(f"📄 Found {len(bill_files)} bills ({'flat uuid files' if flat_mode else 'nested metadata files'})")
        for bill_file in bill_files:
            try:
                with open(bill_file, 'r') as f:
                    bill_data = json.load(f)
                bill = OpenStatesParser._parse_bill_json(bill_data)
                if bill:
                    bills.append(bill)
            except Exception as e:
                print(f"⚠️  Error parsing {bill_file}: {e}")
                continue
        
        print(f"✅ Parsed {len(bills)} unique bills")
        return bills

    @staticmethod
    def _parse_bill_json( dict) -> Optional[Bill]:
        """Parse a single bill JSON file from govbot-openstates-scrapers.

        Supported layouts:
          1) Flat snapshot from `govbot build`: bill fields are at top level.
          2) OpenStates-like JSON: bill.title, bill.identifier, bill.subjects,
             bill.openstates_url, bill.next_action, bill.sponsors, etc.
          3) Legacy nested maps used by earlier prototype scripts.
        """
        try:
            import re

            # Helpers ---------------------------------------------------------
            def first_text(x, *keys):
                """Return first matching key value as string, or ''.

                Searches dict keys in order, allowing nested lookups if value
                is a dict with the next key, but only one level deep.
                """
                for k in keys:
                    if isinstance(x, dict) and k in x:
                        v = x[k]
                        if v is None:
                            continue
                        if isinstance(v, str):
                            return v
                        if isinstance(v, (int, float)):
                            return str(v)
                        if isinstance(v, dict):
                            # common nested shapes: {label: ...}, {name: ...}
                            for kk in ('label', 'name', 'title', 'text', 'value'):
                                if kk in v and v[kk]:
                                    return str(v[kk])
                        if isinstance(v, list) and v:
                            # for sponsor lists etc.
                            return first_text(v[0], 'name', 'title', 'label', 'text')
                return ''

            def as_list(v):
                if v is None:
                    return []
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    return list(v.values())
                return [v]

            def normalize_bill_number(raw: str) -> Optional[str]:
                if not raw:
                    return None
                m = re.search(r'\b([HS][BCR]\d+)\b', raw, re.I)
                return m.group(1).upper() if m else None

            # --- extract identifiers and title --------------------------------
            bill_number = (
                first_text(data, 'identifier') or
                first_text(data, 'bill_number') or
                first_text(data, 'billNumber') or
                first_text(data, 'number') or
                normalize_bill_number(first_text(data, 'title')) or
                normalize_bill_number(first_text(data, 'name'))
            )
            if not bill_number:
                return None

            title = (
                first_text(data, 'title') or
                first_text(data, 'bill_title') or
                first_text(data, 'short_title') or
                first_text(data, 'name') or
                bill_number
            )

            chamber = Chamber.HOUSE if bill_number.startswith('H') else Chamber.SENATE

            # --- sponsors -----------------------------------------------------
            sponsor = first_text(data, 'sponsor') or first_text(data, 'primary_sponsor') or 'Unknown'
            if sponsor == 'Unknown':
                sponsors = as_list(data.get('sponsors') or data.get('primary_sponsors'))
                if sponsors:
                    sponsor = first_text(sponsors[0], 'name', 'title')

            # --- subjects / tags ---------------------------------------------
            subjects = []
            for key in ('subjects', 'subject', 'topics', 'tags', 'categories'):
                v = data.get(key)
                if not v:
                    continue
                for item in as_list(v):
                    if isinstance(item, str):
                        subjects.append(item)
                    elif isinstance(item, dict):
                        txt = first_text(item, 'name', 'title', 'label', 'text')
                        if txt:
                            subjects.append(txt)
            # dedupe while preserving order
            seen_sub = set()
            subjects = [s for s in subjects if not (s in seen_sub or seen_sub.add(s))]

            # --- next reading / action ---------------------------------------
            next_reading = BillReading.FIRST
            next_action = data.get('next_action') or data.get('latest_action') or data.get('action') or {}
            if isinstance(next_action, dict):
                action_desc = (
                    first_text(next_action, 'description') or
                    first_text(next_action, 'action') or
                    first_text(next_action, 'title') or
                    ''
                ).lower()
                if 'third reading' in action_desc:
                    next_reading = BillReading.THIRD
                elif 'second reading' in action_desc:
                    next_reading = BillReading.SECOND

            # --- committee hearing date --------------------------------------
            committee_hearing_date = None
            committee_name = None
            for key in ('committee_hearing_date', 'hearing_date', 'scheduled_date', 'date'):
                raw = first_text(data, key)
                if not raw:
                    continue
                for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d'):
                    try:
                        committee_hearing_date = datetime.strptime(raw.replace('Z', ''), fmt)
                        break
                    except ValueError:
                        continue
                if committee_hearing_date:
                    break
            if isinstance(next_action, dict):
                committee_name = first_text(next_action, 'committee', 'committee_name', 'committeeTitle')
                if not committee_name:
                    committee_name = first_text(next_action.get('committee') or {}, 'name', 'title', 'label')

            # --- ILGA url -----------------------------------------------------
            ilga_url = (
                first_text(data, 'ilga_url') or
                first_text(data, 'openstates_url') or
                first_text(data, 'url') or
                "https://www.ilga.gov/legislation/BillStatus.asp?DocTypeID=" +
                ('HB' if chamber == Chamber.HOUSE else 'SB') +
                "&DocNum=" + re.sub(r'[^\d]', '', bill_number) +
                "&GAID=18&SessionID=114"
            )

            return Bill(
                bill_number=bill_number,
                chamber=chamber,
                title=title,
                sponsor=sponsor,
                next_reading=next_reading,
                subjects=subjects,
                committee_hearing_date=committee_hearing_date,
                committee_name=committee_name,
                ilga_url=ilga_url,
            )
        except Exception as e:
            print(f"⚠️  Error parsing bill: {e}")
            return None

    @staticmethod
    def scrape_ilga_bill_hearings() -> dict:
        """Scrape upcoming bill hearings from active ILGA committee hearing pages.

        Strategy:
          1. Fetch House and Senate committee index pages.
          2. Parse committee codes from committee tables, preferring rows marked
             Scheduled.
          3. Build committee hearing pages from those codes.
          4. Fetch hearing detail pages linked from each committee page.
          5. Scan detail-page HTML for dates/times and bill identifiers.
          6. Fall back to known live detail pages if discovery finds nothing.
        """
        import re

        bill_hearings = {}
        headers = {'User-Agent': 'govbot-urbanist/1.0'}

        detail_href_re = re.compile(
            r'href=["\']([^"\']*/hearings/details/[^"\']+)["\']',
            re.I,
        )
        date_re = re.compile(
            r'(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}\s*[AP]M))?',
            re.I,
        )
        bill_re = re.compile(r'([HS][BCR]\s*\d+)', re.I)
        table_row_re = re.compile(r'^\|([^|]+)\|([A-Z][A-Z0-9-]+)\|([^|]+)\|?$', re.M)
        compact_row_re = re.compile(r'Code:\s*([A-Z][A-Z0-9-]+).*?Hearings:\s*([^|\n]+)', re.S)

        committee_index_urls = [
            ('Senate', 'https://www.ilga.gov/Senate/Committees'),
            ('House', 'https://www.ilga.gov/House/Committees'),
        ]
        seeded_detail_urls = [
            'https://www.ilga.gov/House/Hearings/details/3057/22868',
            'https://www.ilga.gov/House/Hearings/details/3095/22870',
            'https://www.ilga.gov/House/Committees/Hearings/3098',
            'https://www.ilga.gov/Senate/Committees/Hearings/SEXC',
        ]

        committee_pages = []
        seen_committee_pages = set()

        for chamber, index_url in committee_index_urls:
            try:
                resp = requests.get(index_url, timeout=20, headers=headers)
                resp.raise_for_status()
            except Exception as e:
                print(f'   ⚠️  Could not fetch {index_url}: {e}')
                continue

            scheduled_codes = []
            all_codes = []

            for match in table_row_re.finditer(resp.text):
                code = match.group(2).strip().upper()
                status = match.group(3).strip().lower()
                if code in {'CODE', 'NAME'}:
                    continue
                all_codes.append(code)
                if 'scheduled' in status:
                    scheduled_codes.append(code)

            if not all_codes:
                for cm in compact_row_re.finditer(resp.text):
                    code = cm.group(1).strip().upper()
                    status = cm.group(2).strip().lower()
                    if code:
                        all_codes.append(code)
                        if 'scheduled' in status:
                            scheduled_codes.append(code)

            selected_codes = scheduled_codes or all_codes
            print(
                f'   {chamber}: parsed {len(all_codes)} committees '
                f'({len(scheduled_codes)} scheduled, using {len(selected_codes)})'
            )

            for code in selected_codes:
                if not code.startswith(('H', 'S')):
                    continue
                committee_url = f'https://www.ilga.gov/{chamber}/Committees/Hearings/{code}'
                if committee_url not in seen_committee_pages:
                    seen_committee_pages.add(committee_url)
                    committee_pages.append(committee_url)

        print(f'   Discovered {len(committee_pages)} committee hearing pages')

        seen_detail_urls = set()
        detail_urls = []

        for committee_url in committee_pages:
            try:
                resp = requests.get(committee_url, timeout=20, headers=headers)
                resp.raise_for_status()
            except Exception as e:
                print(f'   ⚠️  Could not fetch committee page {committee_url}: {e}')
                continue

            for href in detail_href_re.findall(resp.text):
                detail_url = href if href.startswith('http') else f'https://www.ilga.gov{href}'
                if detail_url not in seen_detail_urls:
                    seen_detail_urls.add(detail_url)
                    detail_urls.append(detail_url)

            if not detail_href_re.search(resp.text):
                detail_urls.append(committee_url)

        print(f'   Discovered {len(detail_urls)} hearing detail pages from committees')

        if not detail_urls:
            print('   ⚠️  No hearing detail pages discovered; using seeded fallback URLs')
            for url in seeded_detail_urls:
                if url not in seen_detail_urls:
                    seen_detail_urls.add(url)
                    detail_urls.append(url)

        for detail_url in detail_urls:
            try:
                dresp = requests.get(detail_url, timeout=20, headers=headers)
                dresp.raise_for_status()
            except Exception as e:
                print(f'   ⚠️  Could not fetch hearing detail {detail_url}: {e}')
                continue

            detail_text = dresp.text
            dm = date_re.search(detail_text)
            if not dm:
                print(f'   ⚠️  No date found on hearing detail {detail_url}')
                continue

            date_str = dm.group(1)
            time_str = (dm.group(2) or '12:00 PM').replace(' ', '')
            try:
                dt = datetime.strptime(f'{date_str} {time_str}', '%m/%d/%Y %I:%M%p')
            except ValueError:
                try:
                    dt = datetime.strptime(date_str, '%m/%d/%Y')
                except ValueError:
                    print(f'   ⚠️  Could not parse hearing date on {detail_url}: {date_str} {time_str}')
                    continue

            matched_bill_count = 0
            for bill_match in bill_re.finditer(detail_text):
                bill_id = re.sub(r'\s+', '', bill_match.group(1).upper())
                if bill_id not in bill_hearings or dt < bill_hearings[bill_id]:
                    bill_hearings[bill_id] = dt
                matched_bill_count += 1

            print(
                f'   📄 {detail_url} -> {matched_bill_count} bill refs '
                f'for {dt.strftime("%b %-d %I:%M%p")}'
            )

        print(f'   Parsed {len(bill_hearings)} unique bills from hearing calendar')
        return bill_hearings

    # Optionally verify witness slip is open on ILGA
