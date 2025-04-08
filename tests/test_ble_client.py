import pytest
from unittest.mock import AsyncMock, patch
from src.ble_client import HeartRateBLEScanner
from src.heart_rate import HeartRateMonitor


@pytest.mark.asyncio
async def test_handle_heart_rate_updates_monitor():
    monitor = HeartRateMonitor()
    scanner = HeartRateBLEScanner(monitor)

    result = []

    def fake_update(hr):
        result.append(hr)

    monitor.update_bluetooth_hr = fake_update
    mock_client = AsyncMock()
    scanner.handle_heart_rate(mock_client, bytearray([0b00000000, 75]))

    assert result == [75]


@pytest.mark.asyncio
async def test_connect_and_monitor_handles_exceptions_gracefully():
    monitor = AsyncMock()
    scanner = HeartRateBLEScanner(monitor)

    with patch("src.ble_client.BleakClient", side_effect=Exception("Mock error")):
        await scanner.connect_and_monitor(AsyncMock())