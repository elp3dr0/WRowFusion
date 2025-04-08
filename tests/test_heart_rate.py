import time

def test_initial_heart_rate(heart_rate_monitor):
    assert heart_rate_monitor.get_heart_rate() == 0

def test_update_and_get_hr(heart_rate_monitor):
    heart_rate_monitor.update_bluetooth_hr(75)
    assert heart_rate_monitor.get_heart_rate() == 75

    # Test recency check (simulate time delay)
    time.sleep(2)
    assert heart_rate_monitor.get_heart_rate() == 75  # still recent

    time.sleep(10)
    assert heart_rate_monitor.get_heart_rate() == 0  # too old, rejected

def test_get_most_recent_hr(heart_rate_monitor):
    heart_rate_monitor.update_bluetooth_hr(75)
    time.sleep(1)
    heart_rate_monitor.update_ant_hr(85)
    assert heart_rate_monitor.get_heart_rate() == 85

    time.sleep(1)
    heart_rate_monitor.update_bluetooth_hr(95)
    assert heart_rate_monitor.get_heart_rate() == 95
