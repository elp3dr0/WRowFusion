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
        
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stroke_rate": random.randint(18, 32),
        "heart_rate": random.randint(120, 160),
        "pace": round(random.uniform(1.8, 2.5), 2),
        "distance": random.randint(1000, 2000),
        "elapsed_time": int(time.time()) % 3600,
        "power": random.randint(180, 280)
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