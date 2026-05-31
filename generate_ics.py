"""
Venue Calendar Feed Generator
Fetches all upcoming events from the Ticketmaster Discovery API
for a given venue and writes them to an .ics file for calendar subscription.

Usage:
  python generate_ics.py --venue "United Center" --city "Chicago" \
      --calendar-name "United Center Chicago" \
      --location "United Center, 1901 W Madison St, Chicago, IL 60612" \
      --output united_center.ics
"""

import os
import sys
import argparse
import requests
from datetime import datetime, date
from icalendar import Calendar, Event
import pytz

API_KEY = os.environ.get("TM_API_KEY")
CHICAGO_TZ = pytz.timezone("America/Chicago")


def get_venue_id(venue_keyword, city):
    """Look up a venue's Ticketmaster Discovery API venue ID by name and city."""
    url = "https://app.ticketmaster.com/discovery/v2/venues.json"
    params = {
        "apikey": API_KEY,
        "keyword": venue_keyword,
        "stateCode": "IL",
        "countryCode": "US",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    venues = data.get("_embedded", {}).get("venues", [])
    for venue in venues:
        name = venue.get("name", "")
        venue_city = venue.get("city", {}).get("name", "")
        if venue_keyword.lower() in name.lower() and city.lower() in venue_city.lower():
            venue_id = venue["id"]
            print(f"Found venue: {name} ({venue_city}) — ID: {venue_id}")
            return venue_id

    raise RuntimeError(
        f"Could not find '{venue_keyword}' in {city} via Ticketmaster venue search. "
        "Check your API key and venue name."
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

    date_str = start.get("dateTime")
    local_date = start.get("localDate")
    local_time = start.get("localTime")
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


def build_calendar(events, calendar_name, location):
    cal = Calendar()
    cal.add("prodid", f"-//{calendar_name}//EN")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", calendar_name)
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
        ev.add("summary", e.get("name", "Event"))
        ev.add("dtstart", dtstart)
        ev.add("uid", f"{e['id']}@venue-calendar")
        ev.add("location", location)

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
    parser = argparse.ArgumentParser(description="Generate an iCal feed for a Ticketmaster venue.")
    parser.add_argument("--venue", required=True, help="Venue name to search for")
    parser.add_argument("--city", default="Chicago", help="City name (default: Chicago)")
    parser.add_argument("--calendar-name", required=True, help="Display name for the calendar")
    parser.add_argument("--location", required=True, help="Full address string for events")
    parser.add_argument("--output", required=True, help="Output .ics filename")
    args = parser.parse_args()

    if not API_KEY:
        print("ERROR: TM_API_KEY environment variable is not set.")
        sys.exit(1)

    print(f"Step 1: Looking up venue ID for '{args.venue}' in {args.city}...")
    venue_id = get_venue_id(args.venue, args.city)

    print(f"\nStep 2: Fetching all events for venue {venue_id}...")
    events = fetch_all_events(venue_id)
    print(f"Total events fetched: {len(events)}")

    print(f"\nStep 3: Building iCal feed '{args.calendar_name}'...")
    cal = build_calendar(events, args.calendar_name, args.location)

    with open(args.output, "wb") as f:
        f.write(cal.to_ical())

    event_count = sum(1 for c in cal.walk() if c.name == "VEVENT")
    print(f"\nDone! Wrote {event_count} events to {args.output}")


if __name__ == "__main__":
    main()
