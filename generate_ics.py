"""
United Center Chicago — Google Calendar Feed Generator
Fetches all upcoming events from the Ticketmaster Discovery API
and writes them to united_center.ics for use as a calendar subscription.
"""

import os
import sys
import requests
from datetime import datetime, date
from icalendar import Calendar, Event
import pytz

API_KEY = os.environ.get("TM_API_KEY")
CHICAGO_TZ = pytz.timezone("America/Chicago")


def get_venue_id():
    """Look up United Center's Ticketmaster Discovery API venue ID."""
    url = "https://app.ticketmaster.com/discovery/v2/venues.json"
    params = {
        "apikey": API_KEY,
        "keyword": "United Center",
        "stateCode": "IL",
        "countryCode": "US",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    venues = data.get("_embedded", {}).get("venues", [])
    for venue in venues:
        name = venue.get("name", "")
        city = venue.get("city", {}).get("name", "")
        if "United Center" in name and "Chicago" in city:
            venue_id = venue["id"]
            print(f"Found venue: {name} ({city}) — ID: {venue_id}")
            return venue_id

    raise RuntimeError(
        "Could not find United Center in Ticketmaster venue search. "
        "Check your API key and try again."
    )


def fetch_all_events(venue_id):
    """Fetch every upcoming event at the venue, handling pagination."""
    events = []
    page = 0

    while True:
        url = "https://app.ticketmaster.com/discovery/v2/events.json"
        params = {
            "apikey": API_KEY,
            "venueId": venue_id,
            "size": 200,
            "page": page,
            "sort": "date,asc",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        page_events = data.get("_embedded", {}).get("events", [])
        events.extend(page_events)

        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)
        current_page = page_info.get("number", 0)
        print(f"  Fetched page {current_page + 1} of {total_pages} ({len(page_events)} events)")

        if current_page >= total_pages - 1:
            break
        page += 1

    return events


def parse_event_datetime(e):
    """Return a dtstart value — timezone-aware datetime or date if time unknown."""
    dates = e.get("dates", {})
    start = dates.get("start", {})

    date_str = start.get("dateTime")        # ISO 8601 with timezone
    local_date = start.get("localDate")     # YYYY-MM-DD
    local_time = start.get("localTime")     # HH:MM:SS (may be absent)
    time_tbd = start.get("timeTBD", False)
    no_specific_time = start.get("noSpecificTime", False)

    if date_str:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(CHICAGO_TZ)

    if local_date:
        if local_time and not time_tbd and not no_specific_time:
            naive = datetime.strptime(f"{local_date} {local_time}", "%Y-%m-%d %H:%M:%S")
            return CHICAGO_TZ.localize(naive)
        else:
            return datetime.strptime(local_date, "%Y-%m-%d").date()

    return None


def build_description(e):
    """Build a readable event description from Ticketmaster metadata."""
    lines = []

    classifications = e.get("classifications", [])
    if classifications:
        c = classifications[0]
        segment = c.get("segment", {}).get("name", "")
        genre = c.get("genre", {}).get("name", "")
        sub_genre = c.get("subGenre", {}).get("name", "")
        if segment and segment != "Undefined":
            lines.append(f"Type: {segment}")
        if genre and genre != "Undefined":
            lines.append(f"Genre: {genre}")
        if sub_genre and sub_genre not in ("Undefined", genre):
            lines.append(f"Sub-genre: {sub_genre}")

    url = e.get("url", "")
    if url:
        lines.append(f"Tickets: {url}")

    info = e.get("info", "")
    if info:
        lines.append(f"\n{info}")

    return "\n".join(lines)


def build_calendar(events):
    cal = Calendar()
    cal.add("prodid", "-//United Center Chicago Events//EN")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", "United Center Chicago")
    cal.add("X-WR-CALDESC", "All public events at United Center — Bulls, Blackhawks, concerts & more")
    cal.add("X-WR-TIMEZONE", "America/Chicago")
    cal.add("REFRESH-INTERVAL;VALUE=DURATION", "PT12H")
    cal.add("X-PUBLISHED-TTL", "PT12H")

    skipped = 0
    for e in events:
        dtstart = parse_event_datetime(e)
        if dtstart is None:
            skipped += 1
            continue

        ev = Event()
        ev.add("summary", e.get("name", "United Center Event"))
        ev.add("dtstart", dtstart)
        ev.add("uid", f"{e['id']}@unitedcenter-chicago-calendar")
        ev.add("location", "United Center, 1901 W Madison St, Chicago, IL 60612")

        description = build_description(e)
        if description:
            ev.add("description", description)

        url = e.get("url", "")
        if url:
            ev.add("url", url)

        cal.add_component(ev)

    if skipped:
        print(f"  Note: skipped {skipped} events with no parseable date")

    return cal


def main():
    if not API_KEY:
        print("ERROR: TM_API_KEY environment variable is not set.")
        sys.exit(1)

    print("Step 1: Looking up United Center venue ID...")
    venue_id = get_venue_id()

    print(f"\nStep 2: Fetching all events for venue {venue_id}...")
    events = fetch_all_events(venue_id)
    print(f"Total events fetched: {len(events)}")

    print("\nStep 3: Building iCal feed...")
    cal = build_calendar(events)

    output_path = "united_center.ics"
    with open(output_path, "wb") as f:
        f.write(cal.to_ical())

    event_count = sum(1 for c in cal.walk() if c.name == "VEVENT")
    print(f"\nDone! Wrote {event_count} events to {output_path}")


if __name__ == "__main__":
    main()
