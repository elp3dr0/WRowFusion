# Lightweight API server for WRowFusion
import logging
import time
import threading

from flask import Flask, jsonify

logger = logging.getLogger(__name__)

# Simulated shared data structure (replace with actual shared data in production)
data_lock = threading.Lock()
current_metrics = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "stroke_rate": 26,
    "heart_rate": 145,
    "pace": 2.05,
    "distance": 1234,
    "elapsed_time": 600,
    "power": 240
}

status_info = {
    "s4_connected": True,
    "hrm_connected": True,
    "hrm_battery": 88,
    "uptime": 3600
}

app = Flask(__name__)

@app.route("/metrics")
def get_metrics():
    with data_lock:
        return jsonify(current_metrics)

@app.route("/status")
def get_status():
    with data_lock:
        return jsonify(status_info)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
