import os
import requests
import datetime
from ics import Calendar, Event

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
existing_events = {}
for event in list(calendar.events):
    if event.name:
        existing_events[event.name] = event

# Date range: past 30 days to future 365 days
start = int((datetime.datetime.utcnow() - datetime.timedelta(days=30)).timestamp())
end = int((datetime.datetime.utcnow() + datetime.timedelta(days=365)).timestamp())

# Query IGDB for games filtered by hypes + follows >= 5
game_query = f"""
fields name, slug, first_release_date, platforms, hypes;
where first_release_date >= {start} & first_release_date <= {end}
  & hypes >= 5;
sort hypes desc;
limit 500;
"""

game_response = requests.post("https://api.igdb.com/v4/games", headers=HEADERS, data=game_query)

if game_response.status_code != 200:
    print("❌ IGDB game API error:", game_response.status_code)
    print(game_response.text)
    exit(1)

games = game_response.json()

if not games:
    print("⚠️ No games returned from IGDB. Try adjusting the filters.")
    exit(0)

# Collect all platform IDs to query names
platform_ids = set()
for game in games:
    platform_ids.update(game.get("platforms", []))

platform_map = {}
if platform_ids:
    platform_query = f"""
    fields id, name;
    where id = ({','.join(map(str, platform_ids))});
    limit 500;
    """
    platform_response = requests.post("https://api.igdb.com/v4/platforms", headers=HEADERS, data=platform_query)

    if platform_response.status_code != 200:
        print("❌ IGDB platform API error:", platform_response.status_code)
        print(platform_response.text)
        exit(1)

    platforms = platform_response.json()
    for p in platforms:
        if "id" in p and "name" in p:
            platform_map[p["id"]] = p["name"]
        else:
            print("⚠️ Skipping invalid platform entry:", p)
else:
    print("⚠️ No platforms found in the game list.")

# Add or update events
added = 0
updated = 0

for game in games:
    name = game.get("name")
    slug = game.get("slug")
    timestamp = game.get("first_release_date")
    game_platforms = game.get("platforms", [])

    if not name or not timestamp:
        continue

    # Format platform list
    if game_platforms:
        platform_names = [platform_map.get(pid, "Unknown") for pid in game_platforms]
        platform_names = sorted(set(platform_names))
    else:
        platform_names = ["Undefined"]

    title = f"{name} [{', '.join(platform_names)}]"
    new_date = datetime.datetime.utcfromtimestamp(timestamp).date()

    existing_event = existing_events.get(title)

    if existing_event:
        old_date = existing_event.begin.date()
        if old_date != new_date:
            calendar.events.remove(existing_event)
            updated += 1
        else:
            continue  # No change needed
    else:
        # Check for same-name event with different platforms (title mismatch)
        replaced = False
        for old_title, old_event in existing_events.items():
            if old_title.startswith(f"{name} ["):
                calendar.events.remove(old_event)
                updated += 1
                replaced = True
                break
        if not replaced:
            added += 1

    # Create event
    event = Event()
    event.name = title
    event.begin = datetime.datetime.combine(new_date, datetime.datetime.min.time())
    event.make_all_day()
    event.description = f"https://www.igdb.com/games/{slug}"

    calendar.events.add(event)
    existing_events[title] = event

# Save calendar file
os.makedirs(os.path.dirname(ICS_FILE), exist_ok=True)
with open(ICS_FILE, "w", encoding="utf-8") as f:
    f.writelines(calendar)

print(f"✔️ Calendar saved to {ICS_FILE}")
print(f"➕ {added} new events added")
print(f"🔁 {updated} existing events updated")
