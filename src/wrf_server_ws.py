import asyncio
import json
import random
import time

import websockets

from src.heart_rate import HeartRateMonitor
from src.s4 import RowerState

clients = set()

# Example simulated metric data
def compile_metrics():
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

async def broadcast():
    while True:
        if clients:
            message = json.dumps(compile_metrics())
            await asyncio.gather(*[client.send(message) for client in clients])
        await asyncio.sleep(1)

async def handler(websocket):
    clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        clients.remove(websocket)

async def ws_task(ws_hr_monitor: HeartRateMonitor, ws_rower_state: RowerState):
    global rower_state
    global hr_monitor

    rower_state = ws_rower_state
    hr_monitor = ws_hr_monitor

    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()