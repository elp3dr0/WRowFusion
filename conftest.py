import pytest
from src.heart_rate import HeartRateMonitor  # Adjust if it's located elsewhere

@pytest.fixture
def heart_rate_monitor():
    return HeartRateMonitor()