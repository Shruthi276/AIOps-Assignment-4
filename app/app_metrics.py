# app/app_metrics.py - all Prometheus metrics for the captioning app

import os
import threading
import time

import psutil
from prometheus_client import Counter, Gauge, Histogram, Info, Summary, start_http_server

METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

APP_INFO = Info("caption_app", "Static information about the captioning app")

# Counters (monotonic, only go up)
REQUESTS = Counter(
    "caption_requests_total",
    "Caption requests (one per Single upload or per Bulk ZIP), with client metadata",
    ["mode", "session_id", "client_ip", "browser"],
)
IMAGES_PROCESSED = Counter(
    "caption_images_processed_total", "Images processed", ["mode", "status"]
)
ERRORS = Counter("caption_errors_total", "Errors by type", ["mode", "error_type"])
BYTES_UPLOADED = Counter("caption_upload_bytes_total", "Image bytes uploaded", ["mode"])
TOKENS_GENERATED = Counter("caption_tokens_generated_total", "Tokens generated", ["mode"])
BULK_ZIPS = Counter("caption_bulk_zips_total", "Bulk ZIP jobs", ["status"])
BULK_FILES_SKIPPED = Counter(
    "caption_bulk_files_skipped_total", "Files inside ZIPs that were skipped", ["reason"]
)
SESSIONS = Counter("caption_sessions_started_total", "New browser sessions", ["browser"])

# Gauges (go up and down) 
ACTIVE_REQUESTS = Gauge("caption_active_requests", "Requests being processed now", ["mode"])
BULK_QUEUE = Gauge("caption_bulk_queue_remaining", "Images left in the current bulk job")
LAST_BATCH_SIZE = Gauge("caption_last_batch_size", "Images in the most recent bulk job")
MODEL_LOADED = Gauge("caption_model_loaded", "1 if the model is loaded in memory")
MODEL_LOAD_SECONDS = Gauge("caption_model_load_seconds", "Model load time at startup")
MODEL_PARAM_BYTES = Gauge("caption_model_parameter_bytes", "Memory held by model weights")
PROCESS_RSS = Gauge("caption_process_memory_bytes", "Resident memory of the app process")
PROCESS_CPU = Gauge("caption_process_cpu_percent", "App process CPU (100 = one full core)")
PROCESS_THREADS = Gauge("caption_process_threads", "Threads in the app process")
LAST_SUCCESS_TS = Gauge(
    "caption_last_success_timestamp_seconds", "Unix time of last successful caption"
)

# Histograms 
INFERENCE_SECONDS = Histogram(
    "caption_inference_seconds", "model.generate() time per image", ["mode"],
    buckets=(0.25, 0.5, 1, 1.5, 2, 3, 5, 8, 13, 20, 30),
)
PREPROCESS_SECONDS = Histogram(
    "caption_preprocess_seconds", "Decode + resize + processor time per image", ["mode"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
)
IMAGE_BYTES = Histogram(
    "caption_image_size_bytes", "Uploaded image file size", ["mode"],
    buckets=(10e3, 50e3, 100e3, 250e3, 500e3, 1e6, 2.5e6, 5e6, 10e6, 20e6),
)
IMAGE_MEGAPIXELS = Histogram(
    "caption_image_megapixels", "Original image resolution", ["mode"],
    buckets=(0.1, 0.3, 0.5, 1, 2, 4, 8, 12, 24),
)
CAPTION_WORDS = Histogram(
    "caption_length_words", "Words per generated caption", ["mode"],
    buckets=(3, 5, 7, 9, 11, 13, 15, 20),
)
BULK_BATCH_IMAGES = Histogram(
    "caption_bulk_batch_images", "Images per bulk ZIP", buckets=(1, 5, 10, 20, 50, 100)
)

# Summaries (_sum and _count) 
REQUEST_SECONDS = Summary(
    "caption_request_duration_seconds",
    "End-to-end time per request (whole Single upload or whole ZIP)", ["mode"],
)
IMAGE_TOTAL_SECONDS = Summary(
    "caption_image_total_seconds", "Preprocess + inference time per image", ["mode"]
)


def _monitor_process(interval=5):
    """Background thread  sample this process's memory/CPU every few seconds."""
    proc = psutil.Process(os.getpid())
    proc.cpu_percent(None)  
    while True:
        PROCESS_RSS.set(proc.memory_info().rss)
        PROCESS_CPU.set(proc.cpu_percent(None))
        PROCESS_THREADS.set(proc.num_threads())
        time.sleep(interval)


_started = False
_lock = threading.Lock()


def start_metrics_server():

    global _started
    with _lock:
        if _started:
            return
        try:
            start_http_server(METRICS_PORT)
        except OSError:
            pass  
        threading.Thread(target=_monitor_process, daemon=True).start()
        _started = True
