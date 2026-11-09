from run_coach.garmin.sync import sync_garmin
from run_coach.storage.db import (
    all_activities,
    all_cycle_entries,
    all_daily_metrics,
    connect,
    init_db,
)


class FakeGarminClient:
    """Stands in for GarminClient: same method surface, no network, no token exchange."""

    def __init__(self):
        self.closed = False

    def search_activities(self, start, end, gaps):
        return [
            {
                "activityId": 1,
                "startTimeGMT": "2026-01-02 06:00:00",
                "activityType": {"typeKey": "running"},
                "distance": 10000.0,
                "movingDuration": 3000.0,
                "averageHR": 148,
                "maxHR": 165,
                "elevationGain": 50.0,
                "calories": 700,
            }
        ]

    def daily_sleep_summaries(self, start, end, gaps):
        return [{"calendarDate": "2026-01-02", "sleepTimeSeconds": 25000, "sleepScores": {"overall": {"value": 80}}}]

    def daily_hrv_summaries(self, start, end, gaps):
        return [{"calendarDate": "2026-01-02", "lastNightAvg": 52}]

    def daily_body_battery(self, start, end, gaps):
        return [{"date": "2026-01-02", "highestBodyBattery": 90, "lowestBodyBattery": 20}]

    def daily_stress(self, start, end, gaps):
        return [{"calendarDate": "2026-01-02", "averageStressLevel": 30}]

    def daily_summaries(self, start, end, gaps):
        return [{"calendarDate": "2026-01-02", "restingHeartRate": 48}]

    def menstrual_cycle_summary(self, day, gaps):
        gaps.append("cycle: fake client returns nothing")

    def close(self):
        self.closed = True


class EmptyGarminClient(FakeGarminClient):
    """Every endpoint fails or returns nothing, to prove a sync never crashes."""

    def search_activities(self, start, end, gaps):
        gaps.append("search_activities: simulated failure")
        return []

    def daily_sleep_summaries(self, start, end, gaps):
        gaps.append("sleep: simulated failure")
        return []

    def daily_hrv_summaries(self, start, end, gaps):
        return []

    def daily_body_battery(self, start, end, gaps):
        return []

    def daily_stress(self, start, end, gaps):
        return []

    def daily_summaries(self, start, end, gaps):
        return []


def test_sync_garmin_populates_storage_from_fake_client(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    result = sync_garmin(conn, days=7, client=FakeGarminClient())
    conn.commit()

    assert result["counts"]["activities"] == 1
    activities = all_activities(conn)
    assert len(activities) == 1
    assert activities[0]["avg_hr"] == 148.0

    metrics = all_daily_metrics(conn)
    assert len(metrics) == 1
    assert metrics[0]["hrv_ms"] == 52
    assert metrics[0]["resting_hr"] == 48

    assert all_cycle_entries(conn) == []
    assert any("cycle" in gap for gap in result["data_gaps"])
    conn.close()


def test_sync_garmin_never_crashes_when_everything_is_missing(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    result = sync_garmin(conn, days=7, client=EmptyGarminClient())
    conn.commit()

    assert result["counts"]["activities"] == 0
    assert all_activities(conn) == []
    assert len(result["data_gaps"]) >= 2
    conn.close()


def test_sync_garmin_closes_injected_client_is_not_assumed(tmp_path):
    # sync_garmin only closes clients it constructs itself, not injected ones,
    # since the caller owns an injected client's lifecycle.
    db_path = tmp_path / "test.db"
    init_db(db_path)
    conn = connect(db_path)

    fake = FakeGarminClient()
    sync_garmin(conn, days=7, client=fake)
    conn.commit()
    conn.close()

    assert fake.closed is False
