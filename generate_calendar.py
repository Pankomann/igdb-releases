import os
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from icalendar import Calendar, Event

# Load credentials from environment
CLIENT_ID = os.environ.get("CLIENT_ID")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")

HEADERS = {
    "Client-ID": CLIENT_ID,
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

ICS_FILE = "docs/igdb_releases.ics"

# Date range: past 30 days to future 365 days (timezone-aware)
now_utc = datetime.now(timezone.utc)
start = int((now_utc - timedelta(days=30)).timestamp())
end = int((now_utc + timedelta(days=365)).timestamp())

# Query IGDB for games with release dates, statuses, and hypes >= 5
GAME_QUERY = f"""
fields name, slug, release_dates.date, release_dates.platform, release_dates.status, hypes;
where first_release_date >= {start} & first_release_date <= {end} & hypes >= 5;
sort release_dates.date asc;
limit 500;
"""

# Helper: safe POST to IGDB
def igdb_post(path: str, query: str):
    url = f"https://api.igdb.com/v4/{path}"
    r = requests.post(url, headers=HEADERS, data=query)
    if r.status_code != 200:
        raise SystemExit(f"❌ IGDB {path} API error: {r.status_code}\n{r.text}")
    return r.json()

# Fetch games
games = igdb_post("games", GAME_QUERY)
if not games:
    print("⚠️ No games returned from IGDB. Try adjusting the filters.")
    raise SystemExit(0)

# Collect platform and status IDs
platform_ids = set()
status_ids = set()
for g in games:
    for rd in g.get("release_dates", []):
        p = rd.get("platform")
        if isinstance(p, int):
            platform_ids.add(p)
        elif isinstance(p, list):
            platform_ids.update(p)
        s = rd.get("status")
        if isinstance(s, int):
            status_ids.add(s)

# Fetch platform and status maps
platform_map = {}
status_map = {}
if platform_ids:
    q = f"fields id,name; where id = ({','.join(map(str, platform_ids))}); limit 500;"
    for p in igdb_post("platforms", q):
        if 'id' in p and 'name' in p:
            platform_map[p['id']] = p['name']

if status_ids:
    q = f"fields id,name; where id = ({','.join(map(str, status_ids))}); limit 500;"
    for s in igdb_post("release_date_statuses", q):
        if 'id' in s and 'name' in s:
            status_map[s['id']] = s['name']

# Group releases by (game_name, release_date, status_name) and collect platforms + slug
grouped = defaultdict(lambda: {"platforms": set(), "slug": None})
for g in games:
    name = g.get("name") or ""
    slug = g.get("slug") or ""
    for rd in g.get("release_dates", []):
        ts = rd.get("date")
        status_id = rd.get("status")
        p = rd.get("platform")
        if not name or not ts or not status_id:
            continue
        release_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        status_name = status_map.get(status_id, "Unknown")
        key = (name, release_date, status_name)
        if isinstance(p, int):
            grouped[key]["platforms"].add(platform_map.get(p, "Unknown"))
        elif isinstance(p, list):
            for pid in p:
                grouped[key]["platforms"].add(platform_map.get(pid, "Unknown"))
        grouped[key]["slug"] = slug

# Load existing calendar (if any) and build summary->date map to detect updates
existing_map = {}
if os.path.exists(ICS_FILE):
    with open(ICS_FILE, "rb") as f:
        try:
            old_cal = Calendar.from_ical(f.read())
            for comp in old_cal.walk():
                if comp.name == "VEVENT":
                    summary = str(comp.get('summary'))
                    dtstart = comp.get('dtstart').dt
                    if isinstance(dtstart, datetime):
                        dtdate = dtstart.date()
                    else:
                        dtdate = dtstart
                    existing_map[summary] = dtdate
        except Exception:
            existing_map = {}

# Build new calendar with proper headers
cal = Calendar()
cal.add('prodid', '-//IGDB Releases//pankomann.github.io//')
cal.add('version', '2.0')
cal.add('calscale', 'GREGORIAN')
cal.add('method', 'PUBLISH')

added = 0
updated = 0

for (name, release_date, status_name), info in grouped.items():
    slug = info.get('slug', '')
    platforms = sorted(info['platforms']) if info['platforms'] else ["Undefined"]
    summary = f"{name} ({status_name}) [{', '.join(platforms)}]"

    # Create UID stable across runs
    uid = f"{slug}-{status_name}-{release_date.isoformat()}@pankomann.github.io"

    # Create VEVENT
    ev = Event()
    ev.add('uid', uid)
    ev.add('summary', summary)
    ev.add('dtstamp', datetime.now(timezone.utc))  # required for RFC compliance
    ev.add('dtstart', release_date)  # all-day event
    ev.add('description', f"https://www.igdb.com/games/{slug}")

    old_date = existing_map.get(summary)
    if old_date is None:
        added += 1
    elif old_date != release_date:
        updated += 1

    cal.add_component(ev)

# Write calendar to disk as iCal bytes (icalendar handles folding, DTSTAMP, UTF-8)
os.makedirs(os.path.dirname(ICS_FILE), exist_ok=True)
with open(ICS_FILE, 'wb') as f:
    f.write(cal.to_ical())

print(f"✔️ Calendar saved to {ICS_FILE}")
print(f"➕ {added} new events added")
print(f"🔁 {updated} existing events updated")