import os
import requests
import datetime
from collections import defaultdict
from ics import Calendar, Event
from dotenv import load_dotenv

# Load credentials from environment
CLIENT_ID = os.environ.get("CLIENT_ID")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")


HEADERS = {
    "Client-ID": CLIENT_ID,
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

ICS_FILE = "docs/igdb_releases.ics"

# Load or initialize the calendar
calendar = Calendar()
if os.path.exists(ICS_FILE):
    with open(ICS_FILE, "r", encoding="utf-8") as f:
        calendar = Calendar(f.read())

# Track existing events by full title
existing_events = {event.name: event for event in calendar.events if event.name}

# Date range: past 30 days to future 365 days
start = int((datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).timestamp())
end = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)).timestamp())

# Query IGDB for games with release dates, statuses, and hypes >= 5
game_query = f"""
fields name, slug, release_dates.date, release_dates.platform, release_dates.status, hypes;
where first_release_date >= {start} & first_release_date <= {end} & hypes >= 5;
sort release_dates.date asc;
limit 500;
"""

response = requests.post("https://api.igdb.com/v4/games", headers=HEADERS, data=game_query)

if response.status_code != 200:
    print(f"❌ IGDB game API error: {response.status_code}")
    print(response.text)
    exit(1)

games = response.json()

if not games:
    print("⚠️ No games returned from IGDB. Try adjusting the filters.")
    exit(0)

# Collect platform and status IDs
platform_ids = set()
status_ids = set()
for game in games:
    for rd in game.get("release_dates", []):
        platform = rd.get("platform")
        if isinstance(platform, int):
            platform_ids.add(platform)
        elif isinstance(platform, list):
            platform_ids.update(platform)
        status = rd.get("status")
        if isinstance(status, int):
            status_ids.add(status)

platform_map = {}
status_map = {}

if platform_ids:
    platform_query = f"""
    fields id, name;
    where id = ({','.join(map(str, platform_ids))});
    limit 500;
    """
    platform_response = requests.post("https://api.igdb.com/v4/platforms", headers=HEADERS, data=platform_query)

    if platform_response.status_code != 200:
        print(f"❌ IGDB platform API error: {platform_response.status_code}")
        print(platform_response.text)
        exit(1)

    for p in platform_response.json():
        if 'id' in p and 'name' in p:
            platform_map[p['id']] = p['name']

if status_ids:
    status_query = f"""
    fields id, name;
    where id = ({','.join(map(str, status_ids))});
    limit 500;
    """
    status_response = requests.post("https://api.igdb.com/v4/release_date_statuses", headers=HEADERS, data=status_query)

    if status_response.status_code != 200:
        print(f"❌ IGDB status API error: {status_response.status_code}")
        print(status_response.text)
        exit(1)

    for s in status_response.json():
        if 'id' in s and 'name' in s:
            status_map[s['id']] = s['name']

# Group releases by (game, date, status)
grouped_releases = defaultdict(lambda: {"platforms": set(), "slug": None})

for game in games:
    name = game.get("name")  # Use as-is; ics library handles UTF-8
    slug = game.get("slug")
    for rd in game.get("release_dates", []):
        date = rd.get("date")
        status_id = rd.get("status")
        platform = rd.get("platform")

        if not name or not date or not status_id:
            continue

        release_date = datetime.datetime.fromtimestamp(date, tz=datetime.timezone.utc).date()
        status_name = status_map.get(status_id, "Unknown")

        key = (name, release_date, status_name)
        if isinstance(platform, int):
            grouped_releases[key]["platforms"].add(platform_map.get(platform, "Unknown"))
        elif isinstance(platform, list):
            for pid in platform:
                grouped_releases[key]["platforms"].add(platform_map.get(pid, "Unknown"))

        grouped_releases[key]["slug"] = slug

# Add or update events
added = 0
updated = 0

for (name, release_date, status_name), info in grouped_releases.items():
    slug = info["slug"]
    platform_names = sorted(info["platforms"]) if info["platforms"] else ["Undefined"]

    title = f"{name} ({status_name}) [{', '.join(platform_names)}]"
    existing_event = existing_events.get(title)

    if existing_event:
        if existing_event.begin.date() != release_date:
            calendar.events.discard(existing_event)
            updated += 1
        else:
            continue
    else:
        for old_title, old_event in list(existing_events.items()):
            if old_title == title and old_event.begin.date() != release_date:
                calendar.events.discard(old_event)
                updated += 1
                break
        added += 1

    event = Event()
    event.name = title
    event.begin = datetime.datetime.combine(release_date, datetime.datetime.min.time())
    event.make_all_day()
    event.description = f"https://www.igdb.com/games/{slug}"

    calendar.events.add(event)
    existing_events[title] = event

os.makedirs(os.path.dirname(ICS_FILE), exist_ok=True)
with open(ICS_FILE, "w", encoding="utf-8") as f:
    f.writelines(calendar)

print(f"✔️ Calendar saved to {ICS_FILE}")
print(f"➕ {added} new events added")
print(f"� {updated} existing events updated")