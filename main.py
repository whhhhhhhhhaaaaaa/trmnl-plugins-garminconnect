from fastapi import FastAPI
from garminconnect import Garmin
from datetime import date, datetime, timezone
import os

app = FastAPI()

EMAIL = os.getenv("GARMIN_EMAIL")
PASSWORD = os.getenv("GARMIN_PASSWORD")

RIDE_KEYWORDS = ("cycl", "bik", "ride")  # fallback only


def find_last_ride(client):
    # 1. Garmin's own category filter — covers every bike subtype
    #    (road, gravel, mountain, indoor, virtual) regardless of age.
    try:
        rides = client.get_activities(0, 1, activitytype="cycling")
        if rides:
            return rides[0]
    except Exception:
        pass

    # 2. Fallback: wider window, substring match, in case something
    #    was mislabeled and missed the category filter.
    try:
        for act in client.get_activities(0, 50):
            type_key = (act.get("activityType") or {}).get("typeKey", "")
            if any(k in type_key for k in RIDE_KEYWORDS):
                return act
    except Exception:
        pass

    return None


def n(value, default=0):
    """Coalesce None/missing -> default so Liquid never renders blank."""
    return value if value is not None else default


@app.get("/trmnl")
def today():
    client = Garmin(EMAIL, PASSWORD)
    client.login()

    stats = client.get_stats(date.today().isoformat())

    try:
        sleep_dto = client.get_sleep_data(date.today().isoformat()).get("dailySleepDTO") or {}
    except Exception:
        sleep_dto = {}

    last_sync = datetime.fromisoformat(stats["lastSyncTimestampGMT"]).replace(tzinfo=timezone.utc)
    minutes_ago = int((datetime.now(timezone.utc) - last_sync).total_seconds() / 60)

    sleep_seconds = n(sleep_dto.get("sleepTimeSeconds"), 0)
    sleep_score = ((sleep_dto.get("sleepScores") or {}).get("overall") or {}).get("value")

    moderate = n(stats.get("moderateIntensityMinutes"), 0)
    vigorous = n(stats.get("vigorousIntensityMinutes"), 0)
    goal = n(stats.get("dailyStepGoal"), 10000)
    steps = n(stats.get("totalSteps"), 0)

    payload = {
        "last_sync": last_sync.strftime("%H:%M"),
        "minutes_since_sync": minutes_ago,
        # today — every field has an explicit default
        "steps": steps,
        "goal": goal,
        "progress": round(steps / goal * 100) if goal else 0,
        "sleep_hours": round(sleep_seconds / 3600, 1),
        "sleep_score": sleep_score,  # None is fine — template hides the line
        "body_battery": n(stats.get("bodyBatteryMostRecentValue"), 0),
        "body_battery_charged": n(stats.get("bodyBatteryChargedValue"), 0),
        "body_battery_drained": n(stats.get("bodyBatteryDrainedValue"), 0),
        "resting_hr": n(stats.get("restingHeartRate"), 0),
        "hr_7day_avg": n(stats.get("lastSevenDaysAvgRestingHeartRate"), 0),
        "intensity_minutes": moderate + (2 * vigorous),
        "intensity_minutes_goal": n(stats.get("intensityMinutesGoal"), 150),
    }

    ride = find_last_ride(client)
    if ride:
        avg_power = ride.get("avgPower")
        avg_hr = ride.get("averageHR")
        started_local = ride.get("startTimeLocal") or ""
        ride_date_str = started_local[:10] if started_local else None

        ride_when = "-"
        if ride_date_str:
            days_ago = (date.today() - datetime.strptime(ride_date_str, "%Y-%m-%d").date()).days
            ride_when = "Today" if days_ago == 0 else "Yesterday" if days_ago == 1 else f"{days_ago} days ago"

        payload.update({
            "has_ride": True,
            "ride_name": ride.get("activityName") or "Ride",
            "ride_when": ride_when,
            "ride_distance_km": round(n(ride.get("distance"), 0) / 1000, 1),
            "ride_duration_min": round(n(ride.get("duration"), 0) / 60),
            "ride_avg_speed_kmh": round(n(ride.get("averageSpeed"), 0) * 3.6, 1),
            "ride_elevation_gain": round(n(ride.get("elevationGain"), 0)),
            "ride_avg_power": round(avg_power) if avg_power else None,
            "ride_avg_hr": round(avg_hr) if avg_hr else None,
        })
    else:
        payload.update({
            "has_ride": False,
            "ride_name": "-", "ride_when": "-",
            "ride_distance_km": 0, "ride_duration_min": 0,
            "ride_avg_speed_kmh": 0, "ride_elevation_gain": 0,
            "ride_avg_power": None, "ride_avg_hr": None,
        })

    return payload