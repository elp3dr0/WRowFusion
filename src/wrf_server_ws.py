import logging
import asyncio
import json
import time

from websockets.legacy.server import (
    serve,
    WebSocketServerProtocol,
    )
from src.heart_rate import HeartRateMonitor
from src.s4 import RowerState

logger = logging.getLogger(__name__)

clients: set[WebSocketServerProtocol] = set()

# Example simulated metric data
def compile_metrics(rower_state: RowerState, hr_monitor: HeartRateMonitor) -> dict[str, int | float | str]:
    logger.debug("Compiling metrics")
    wr_values = rower_state.get_WRValues()
    wr_values = hr_monitor.inject_heart_rate(wr_values)
    
    # Still to add:
    #'stroke_count': 0,
    #'speed_cmps': 0,
    #'total_calories': 0,
    #'stroke_ratio': 0.0,

    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stroke_rate": wr_values.get('stroke_rate_pm', 0),
        "heart_rate": wr_values.get('heart_rate_bpm', 0),
        "pace": wr_values.get('instant_500m_pace_secs', 0),
        "distance": wr_values.get('total_distance_m', 0),
        "elapsed_time": wr_values.get('elapsed_time_secs', 0),
        "power": wr_values.get('instant_watts', 0),
    }

async def broadcast(rower_state: RowerState, hr_monitor: HeartRateMonitor) -> None:
    logger.debug("Preparing broadcast loop")
    while True:
        if clients:
            message = json.dumps(compile_metrics(rower_state, hr_monitor))
            await asyncio.gather(*[client.send(message) for client in clients])
        await asyncio.sleep(1)

async def handler(websocket: WebSocketServerProtocol) -> None:
    logger.debug("Handling new client connection")
    clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clients.remove(websocket)

async def ws_task(rower_state: RowerState, hr_monitor: HeartRateMonitor) -> None:
    logger.debug("Starting websocket server")
    async with serve(handler, "0.0.0.0", 8765):
        await asyncio.gather(
            broadcast(rower_state, hr_monitor),
            asyncio.Future()
        )
        