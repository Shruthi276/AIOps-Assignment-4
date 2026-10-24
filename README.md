# DA3408 · Assignment 4 — Application Monitoring with Prometheus & Grafana

---

## Table of contents
1. [What is in this repository](#1-what-is-in-this-repository)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Setup](#4-setup)
5. [Running the stack](#5-running-the-stack)
6. [Grafana: data source and dashboard import](#6-grafana-data-source-and-dashboard-import)
7. [Using the app](#7-using-the-app)
8. [Metrics reference](#8-metrics-reference)
9. [How the key metrics are calculated](#9-how-the-key-metrics-are-calculated)
10. [Alerting](#10-alerting)
11. [Dashboard design](#11-dashboard-design)
12. [AI Disclosure (Fair Use of AI)](#12-ai-disclosure-fair-use-of-ai)

---

## 1. What is in this repository

```
.
├── README.md                     ← this guide
├── requirements.txt              ← Python dependencies (CPU-only PyTorch)
├── .gitignore
├── .streamlit/
│   └── config.toml               ← Streamlit settings
├── app/
│   ├── app.py                    ← Streamlit UI (Single + Bulk ZIP)
│   ├── app_metrics.py            ← every Prometheus metric + /metrics server
│   └── captioner.py              ← BLIP model loading + captioning
├── prometheus/
│   ├── prometheus.yml            ← scrape config
│   └── alert_rules.yml           ← alert rules
├── alertmanager/
│   └── alertmanager.yml          ← alert routing
└── grafana/
    ├── dashboard_export.json     ← Grafana dashboard (import this)
    └── dashboard_demo.mov        ← ~1 min screen recording of the live dashboard
```

| File | What it contains |
|---|---|
| `app/app.py` | Streamlit UI. **Single** tab: upload one image → caption. **Bulk** tab: upload a ZIP → captions for every image, results table + CSV download. Records request-level metrics and client labels (session ID, IP, browser). |
| `app/app_metrics.py` | Definitions of **every** Prometheus metric (Counters, Gauges, Histograms, Summaries, Info), the `/metrics` HTTP server on port **8000**, and a background thread sampling the app's own memory/CPU every 5 s. |
| `app/captioner.py` | Loads `Salesforce/blip-image-captioning-base` on CPU, runs one warm-up inference, and captions one image (returns caption + timings). |
| `.streamlit/config.toml` | Streamlit settings: port 8501, 200 MB upload limit, headless mode. |
| `requirements.txt` | Python dependencies. |
| `prometheus/prometheus.yml` | Prometheus config: scrapes the app (`:8000`), node_exporter (`:9100`), itself (`:9090`) and Alertmanager (`:9093`) every 5 s; loads alert rules; sends firing alerts to Alertmanager. |
| `prometheus/alert_rules.yml` | 6 alert rules (app down, node_exporter down, high p95 latency, caption errors, high CPU, low memory). |
| `alertmanager/alertmanager.yml` | Alertmanager routing: groups alerts by name; alerts are viewed in the Alertmanager UI and in Grafana. |
| `grafana/dashboard_export.json` | Exported Grafana dashboard (33 panels in 7 rows). |
| `grafana/dashboard_demo.mov` | About one minute of screen recording of the live dashboard with the 5 s auto-refresh on. |

---

## 2. Architecture

```
  Browser ──► Streamlit app :8501 ──► BLIP model (CPU)
                    │
                    └── /metrics :8000 ◄───────┐
                                               │  scraped every 5 s
  node_exporter :9100 (CPU/RAM/disk/net) ◄─────┤
                                               │
                                     Prometheus :9090 ──► alert rules ──► Alertmanager :9093
                                               ▲
                                               │  PromQL queries
                                   Grafana :3000 (Docker)
```

| Component | Port | URL |
|---|---|---|
| Streamlit app | 8501 | http://localhost:8501 |
| App metrics endpoint | 8000 | http://localhost:8000/metrics |
| node_exporter | 9100 | http://localhost:9100/metrics |
| Prometheus | 9090 | http://localhost:9090 |
| Alertmanager | 9093 | http://localhost:9093 |
| Grafana | 3000 | http://localhost:3000 (login admin / admin) |

---

## 3. Prerequisites

Tested on Ubuntu (VirtualBox VM, 8+ GB RAM, 2+ CPUs). No GPU is needed.

| Tool | Version used |
|---|---|
| Python | 3.10+ |
| PyTorch | 2.14.1+cpu |
| Prometheus | 3.15.0 (linux-amd64) |
| Alertmanager | 0.34.1 (linux-amd64) |
| node_exporter | 1.12.1 (linux-amd64) |
| Grafana | `grafana/grafana-enterprise` Docker image |
| Docker | any recent version |

---

## 4. Setup

### 4.1 Clone and install the app
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git zip
git clone https://github.com/Shruthi276/AIOps-Assignment-4.git
cd AIOps-Assignment-4
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```


### 4.2 Prometheus, Alertmanager, node_exporter
Download the **linux-amd64** archives of  Prometheus, AlertManager, and Node Exporter from https://prometheus.io/download/
into `~/monitoring`, then extract them and create short names:
```bash
mkdir -p ~/monitoring && cd ~/monitoring
for f in *.tar.gz; do tar xzf "$f"; done
ln -sfn "$(ls -d prometheus-*linux-amd64 | head -1)"    prometheus
ln -sfn "$(ls -d alertmanager-*linux-amd64 | head -1)"  alertmanager
ln -sfn "$(ls -d node_exporter-*linux-amd64 | head -1)" node_exporter
```

### 4.3 Grafana (Docker)
```bash
docker pull grafana/grafana-enterprise
docker run -d -p 3000:3000 --name=grafana grafana/grafana-enterprise   # first time only
```
On later runs use `docker start grafana`.

---

## 5. Running the stack

Open one terminal per component and run every command **from the repository root**.

| # | Component | Command |
|---|---|---|
| 1 | node_exporter | `~/monitoring/node_exporter/node_exporter` |
| 2 | Prometheus | `~/monitoring/prometheus/prometheus --config.file=prometheus/prometheus.yml --storage.tsdb.path=$HOME/monitoring/prometheus-data` |
| 3 | Alertmanager | `~/monitoring/alertmanager/alertmanager --config.file=alertmanager/alertmanager.yml --storage.path=$HOME/monitoring/alertmanager-data` |
| 4 | Grafana | `docker start grafana` |
| 5 | App | `source venv/bin/activate && streamlit run app/app.py` |

**Verify:** open http://localhost:9090/targets — all 4 targets (`caption_app`, `node`,
`prometheus`, `alertmanager`) must show **UP**.



---

## 6. Grafana: data source and dashboard import

**6.1 Add the Prometheus data source.** Grafana runs inside Docker, where `localhost` means the
container itself, so it reaches Prometheus through the Docker bridge IP (check with `ip -4 addr show docker0`). The dashboard expects the data source UID `prometheus-local`:
```bash
curl -s -u admin:admin -H "Content-Type: application/json" -X POST http://localhost:3000/api/datasources \
  -d '{"name":"Prometheus-A4","type":"prometheus","uid":"prometheus-local","access":"proxy","url":"http://172.17.0.1:9090","isDefault":true,"jsonData":{"timeInterval":"5s"}}'
```

**6.2 Import the dashboard.** In Grafana: **Dashboards → New → Import → Upload dashboard JSON file**
→ select `grafana/dashboard_export.json` → **Import**.

The dashboard opens with a **5 s** auto-refresh and a 15-minute time window.

---

## 7. Using the app

Open http://localhost:8501.

- **Single image tab** — upload a JPG/PNG/BMP/WEBP → *Generate caption* → caption, inference time, preprocess time, image size.
- **Bulk (ZIP) tab** — upload a ZIP → *Caption all images* → progress bar, results table, CSV download.
  - Up to 100 images per ZIP, max 20 MB per image.
  - Non-image, hidden (`.`) and `__MACOSX/` files are skipped and counted.
  - A corrupt or non-ZIP file shows an error message instead of crashing the app.
  - Images are downscaled to 768 px before inference to keep CPU load reasonable.
- **Sidebar** — shows the session ID, client IP and browser that are attached as metric labels.

**Create test files:**
```bash
mkdir -p sample_data/bulk && cd sample_data
for i in $(seq 1 40); do wget -q -O bulk/img_$i.jpg "https://picsum.photos/seed/$i/800/600"; done
echo "not an image" > bulk/notes.txt
zip -j test_bulk.zip bulk/*        # 40 images + 1 file that will be skipped
echo "not a zip" > fake.zip        # triggers the BadZipFile error path
cd ..
```

---

## 8. Metrics reference

All app metrics start with `caption_` and are exposed at http://localhost:8000/metrics.
Defined in `app/app_metrics.py`.

### Counters (only increase; reset when the app restarts)
| Metric | Labels | Meaning |
|---|---|---|
| `caption_requests_total` | `mode`, `session_id`, `client_ip`, `browser` | One per Single upload or per ZIP — **carries the client metadata labels** |
| `caption_images_processed_total` | `mode`, `status` | Images captioned (`success` / `error`) |
| `caption_errors_total` | `mode`, `error_type` | Exceptions by class name, e.g. `BadZipFile` |
| `caption_upload_bytes_total` | `mode` | Bytes of image data received |
| `caption_tokens_generated_total` | `mode` | Tokens produced by the model |
| `caption_bulk_zips_total` | `status` | ZIP jobs `completed` / `rejected` |
| `caption_bulk_files_skipped_total` | `reason` | `not_an_image`, `hidden_or_system`, `too_large`, `over_limit` |
| `caption_sessions_started_total` | `browser` | New browser sessions |

### Gauges (current value, can go up or down)
| Metric | Labels | Meaning |
|---|---|---|
| `caption_active_requests` | `mode` | Requests being processed right now |
| `caption_bulk_queue_remaining` | — | Images left in the running bulk job |
| `caption_last_batch_size` | — | Images in the latest ZIP |
| `caption_model_loaded` | — | 1 when the model is in memory |
| `caption_model_load_seconds` | — | Model load time at startup |
| `caption_model_parameter_bytes` | — | Memory held by model weights |
| `caption_process_memory_bytes` | — | App process resident memory (RSS) |
| `caption_process_cpu_percent` | — | App process CPU (100 = one full core) |
| `caption_process_threads` | — | Threads in the app process |
| `caption_last_success_timestamp_seconds` | — | Unix time of the last successful caption |

### Histograms (`_bucket`, `_sum`, `_count`)
| Metric | Labels | Buckets |
|---|---|---|
| `caption_inference_seconds` | `mode` | 0.25 … 30 s |
| `caption_preprocess_seconds` | `mode` | 0.01 … 2 s |
| `caption_image_size_bytes` | `mode` | 10 kB … 20 MB |
| `caption_image_megapixels` | `mode` | 0.1 … 24 MP |
| `caption_length_words` | `mode` | 3 … 20 words |
| `caption_bulk_batch_images` | — | 1 … 100 images |

### Summaries (`_sum` and `_count`)
| Metric | Labels | Meaning |
|---|---|---|
| `caption_request_duration_seconds` | `mode` | End-to-end time per request (whole upload or whole ZIP) |
| `caption_image_total_seconds` | `mode` | Preprocess + inference time per image |

### Info
`caption_app_info{model, device, torch_version}` — static build information.

### Design note on labels
Client labels (`session_id`, `client_ip`, `browser`) are attached **only** to
`caption_requests_total`. Adding them to histograms would multiply every bucket by every
session (*cardinality explosion*), so latency metrics are labelled only by `mode`.

### System metrics (from node_exporter)
`node_cpu_seconds_total`, `node_memory_MemTotal_bytes`, `node_memory_MemAvailable_bytes`,
`node_memory_SwapTotal_bytes` / `SwapFree_bytes`, `node_load1/5/15`,
`node_disk_read_bytes_total` / `written_bytes_total`, `node_filesystem_avail_bytes` / `size_bytes`,
`node_network_receive_bytes_total` / `transmit_bytes_total`.

---

## 9. How the key metrics are calculated

| Quantity | PromQL | Logic, with a worked example |
|---|---|---|
| App up/down | `up{job="caption_app"}` | Set by Prometheus on every scrape: 1 = scrape succeeded, 0 = failed. |
| Throughput | `rate(caption_images_processed_total[1m])` | Per-second increase of a counter over 1 min. Counter goes 100 → 130 in 60 s ⇒ 30 / 60 = **0.5 images/s**. |
| Requests per minute | `rate(caption_requests_total[1m]) * 60` | Same as above, × 60 to turn per-second into per-minute. |
| Average time per image | `rate(..._sum[2m]) / rate(..._count[2m])` | Summary: `_sum` grew by 45 s while `_count` grew by 30 ⇒ 45 / 30 = **1.5 s per image**. |
| p95 latency | `histogram_quantile(0.95, sum by (le) (rate(caption_inference_seconds_bucket[2m])))` | Buckets are cumulative. With 100 images: 60 ≤ 1.5 s, 90 ≤ 2 s, 100 ≤ 3 s. The 95th image is in the 2–3 s bucket, 5 of its 10 images in ⇒ linear interpolation ⇒ 2 + 0.5 × 1 = **2.5 s**. |
| Host CPU % | `100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])))` | `rate` of idle seconds = fraction of time each core was idle. Average over cores; busy = 1 − idle. Idle 0.3 ⇒ **70 %**. |
| Busy cores | `sum(rate(node_cpu_seconds_total{mode!="idle"}[1m]))` | Non-idle seconds per second, summed over cores. Compared with `caption_process_cpu_percent / 100` to see how much of the load is the app. |
| RAM used % | `100 * (1 - MemAvailable / MemTotal)` | 1.5 GB available of 6 GB ⇒ 1 − 0.25 ⇒ **75 %**. |

---

## 10. Alerting

Prometheus evaluates `prometheus/alert_rules.yml` every 5 s and forwards firing alerts to
Alertmanager (the `alerting:` section of `prometheus/prometheus.yml`).

| Alert | Condition | For | Severity |
|---|---|---|---|
| `CaptionAppDown` | `up{job="caption_app"} == 0` | 30 s | critical |
| `NodeExporterDown` | `up{job="node"} == 0` | 30 s | critical |
| `HighInferenceLatencyP95` | p95 inference > 5 s | 1 min | warning |
| `CaptionErrors` | any errors in the last 5 min | — | warning |
| `HighCPU` | host CPU > 90 % | 2 min | warning |
| `LowMemory` | available RAM < 10 % | 2 min | warning |

**Test the pipeline:** stop the Streamlit app (Ctrl+C). After ~30 s, `CaptionAppDown` turns
*Firing* at http://localhost:9090/alerts and appears at http://localhost:9093. Restart the app and
the alert resolves. Firing alerts also show as red annotation markers on Grafana time-series panels.

---

## 11. Dashboard design

The layout flows **from high-level health down to low-level resources**:

| Row | Question it answers | Panels |
|---|---|---|
| 1 Service health | Is everything up? | Reading guide, App status, node_exporter status, Model loaded, Firing alerts, App uptime, Time since last caption |
| 2 Traffic & throughput | How much work? | Images/s by mode, Requests/min by mode, Totals |
| 3 Latency | How fast? | p50/p95/p99 inference, Average time per image (Summary), Latency heatmap |
| 4 Workload & clients | What is queued, what failed, who is calling? | In-flight work, Skipped files, Errors, Requests-by-client table (custom labels) |
| 5 Correlation | Does app load drive hardware usage? | Throughput vs host CPU (dual axis), App vs host CPU cores, App vs host memory |
| 6 System resources | CPU, RAM, load | CPU by mode, Memory & swap %, Load vs cores |
| 7 Disk & network | I/O | Disk throughput, Disk space used, Network throughput |

A shared crosshair links all panels: hovering over one moment marks the same moment everywhere,
so a bulk upload can be lined up directly with the CPU and memory spike.

**Demo recording:** [`grafana/dashboard_demo.mov`](grafana/dashboard_demo.mov) shows about one minute of the
dashboard running live with the **5 s** auto-refresh, so you can see the panels update as new data is scraped.

### 7 Commandments of Plotting
| Commandment | Implementation |
|---|---|
| Colour-blind-inclusive palette | Okabe-Ito colours on every series; Viridis on the heatmap; status uses blue/vermillion instead of green/red |
| Markers relevant across media | Each series has its own line style (solid / dashed / dotted); status panels show text (UP ✓ / DOWN ✗), so nothing relies on colour alone |
| Axes named | Every y-axis has a label; every panel description states that the x-axis is wall-clock time |
| Scale and units explicit | Each axis label states its scale "(linear)"; units are set per panel (s, %, bytes, B/s, count) |
| Legend when > 1 variable | Table legend with mean / max / last on every multi-series panel |
| Title (and subtitle) | Row titles act as section headings; every panel has its own title |
| Short story | Every panel has an ⓘ description; a "How to read this dashboard" panel sits at the top |

---



## 12. AI Disclosure (Fair Use of AI)

**1. Which tools were used:** Claude 

**2. How they were used:**
- Used Claude to generate the PromQL queries for my Grafana dashboard, mainly the
  `histogram_quantile` p50/p95/p99 latency panels, host CPU % from `node_cpu_seconds_total`, and
  the average time per image (`_sum` / `_count`) panels. 
- Used Claude for the complex regex and PromQL, such as the `device!~"lo|docker.*|veth.*"` and
  `device!~"loop.*|sr.*"` filters that drop virtual network and disk devices, and the p95 latency
  and CPU % alert expressions. 
- Used Claude to debug issue Streamlit re-runs the whole script on every
  click, so `start_http_server(8000)` ran again and crashed with *"Address already in use"*.
  Claude suggested starting the metrics server only once, inside a `@st.cache_resource` function
  with a lock and a `_started` flag (`app/app.py`, `app/app_metrics.py`) and also helped in how to read
  the client's IP and browser for the metric labels, which led me to `st.context.headers`.


**3. Impact:** Claude helped in PromQL syntax and on fixing the metrics server crash. I chose
the metrics, labels, dashboard layout and alert thresholds myself, and I worked through every
AI-generated query by hand  before using it.



### Manual calculation of the  metrics
I worked through each of these by hand to check that the query gives the right number:

- **p95 latency (`histogram_quantile`)**: `rate(..._bucket[2m])` gives the per-second increase
  of each cumulative bucket, and `sum by (le)` adds the `single` and `bulk` modes together while
  keeping the bucket boundaries. Suppose 100 images were captioned in the window: 60 were ≤ 1.5 s,
  90 were ≤ 2 s and 100 were ≤ 3 s. The 95th image is in the 2–3 s bucket, which holds images
  91–100. It is the 5th of those 10, so Prometheus interpolates linearly:
  2 + (5/10) × (3 − 2) = **2.5 s**. That is below 5 s, so `HighInferenceLatencyP95` does not fire.
- **Host CPU %**: on a 2-core VM, `rate(node_cpu_seconds_total{mode="idle"}[1m])` gives 0.20 for
  cpu0 and 0.40 for cpu1 (the share of each second the core was idle). `avg` = 0.30, so
  CPU % = 100 × (1 − 0.30) = **70 %**. That is below 90 %, so `HighCPU` does not fire.
- **Regex filters**: `!~` keeps only the series whose label does **not** match the regex.
  `lo|docker.*|veth.*` removes the loopback, `docker0` and every `veth…` container interface, so
  the network panel only counts the real NIC (e.g. `enp0s3`). Without the filter, traffic between
  Grafana and Prometheus would be counted twice: once on `docker0` and once on `veth…`.
- **Time since last caption**: `caption_last_success_timestamp_seconds > 0` drops the series while
  the gauge is still 0, i.e. before the first caption. If the last caption was at 1 761 300 000
  and `time()` is 1 761 300 042, the panel shows **42 s**.
