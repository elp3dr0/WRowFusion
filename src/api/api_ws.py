import logging
import asyncio
import json
import time

from websockets.legacy.server import (
    serve,
    WebSocketServerProtocol,
    )
from src.hr.heart_rate import HeartRateMonitor
from src.s4.s4 import RowerState

logger = logging.getLogger(__name__)

clients: set[WebSocketServerProtocol] = set()

# Example simulated metric data
def compile_metrics(rower_state: RowerState, hr_monitor: HeartRateMonitor) -> dict[str, int | float | str]:
    logger.debug("Compiling metrics")
    wr_values = rower_state.get_WRValues()
    wr_values = hr_monitor.inject_heart_rate(wr_values)
    

    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stroke_rate_pm": wr_values.get('stroke_rate_pm', 0),
        "stroke_count": wr_values.get('stroke_count', 0),
        "heart_rate_bpm": wr_values.get('heart_rate_bpm', 0),
        "pace_mmss": f"{(s := wr_values.get('instant_500m_pace_secs', 0)) // 60}:{s % 60:02}",
        "speed_mps": round(wr_values.get('speed_cmps', 0)/100, 2),
        "total_distance_m": wr_values.get('total_distance_m', 0),
        "elapsed_time": wr_values.get('elapsed_time_secs', 0),
        "instant_watts": wr_values.get('instant_watts', 0),
        "total_calories": round(wr_values.get('total_calories', 0)/1000,1),
        "stroke_ratio": round(wr_values.get('stroke_ratio', 0),2)
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
        