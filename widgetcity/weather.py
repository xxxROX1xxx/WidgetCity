import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fetch(url, params):
    request = Request(f"{url}?{urlencode(params)}", headers={"User-Agent": "WidgetCity"})
    with urlopen(request, timeout=6) as response:
        return json.load(response)


def forecast(city):
    places = fetch("https://geocoding-api.open-meteo.com/v1/search",
                   {"name": city, "count": 1, "language": "ru"}).get("results", [])
    if not places:
        raise LookupError("Город не найден. Укажите название, при необходимости через запятую добавьте регион.")
    place = places[0]
    data = fetch("https://api.open-meteo.com/v1/forecast", {
        "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
        "current": "temperature_2m,rain,showers,wind_direction_10m",
        "hourly": "temperature_2m,precipitation_probability", "forecast_days": 2,
    })
    current = data["current"]
    hourly = data["hourly"]
    slots = [[time, temp, rain] for time, temp, rain in zip(
        hourly["time"], hourly["temperature_2m"], hourly["precipitation_probability"]
    ) if time >= current["time"][:13] + ":00"]
    name = ", ".join(dict.fromkeys(place[key] for key in ("name", "admin1", "country") if place.get(key)))
    return {
        "query": city, "place": name, "temperature": current["temperature_2m"],
        "raining": bool((current.get("rain") or 0) + (current.get("showers") or 0)),
        "wind": current["wind_direction_10m"], "hourly": slots[:12],
        "updated": datetime.now().astimezone().isoformat(timespec="minutes"),
    }
