# app/app.py - Streamlit UI for CPU image captioning, instrumented with Prometheus.
# AI-assisted (Claude); logic reviewed and understood by me.
import io
import uuid
import zipfile

import pandas as pd
import streamlit as st
import torch

from captioner import MODEL_NAME, caption_image, load_model

MAX_IMAGES_PER_ZIP = 100
MAX_IMAGE_MB = 20
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

st.set_page_config(page_title="CPU Image Captioning", page_icon="🖼️", layout="wide")


@st.cache_resource
def get_metrics():
    # Streamlit reruns this script on every interaction. Importing inside a
    # cached function registers metrics and starts /metrics only once.
    import app_metrics
    app_metrics.start_metrics_server()
    return app_metrics


m = get_metrics()


@st.cache_resource(show_spinner="Loading BLIP model on CPU (first run only)...")
def get_model():
    processor, model, load_s, param_bytes = load_model()
    m.MODEL_LOADED.set(1)
    m.MODEL_LOAD_SECONDS.set(load_s)
    m.MODEL_PARAM_BYTES.set(param_bytes)
    m.APP_INFO.info({"model": MODEL_NAME, "device": "cpu", "torch_version": torch.__version__})
    return processor, model


processor, model = get_model()


def client_meta():
    """Session ID, client IP and browser family, used as Prometheus labels."""
    headers = st.context.headers
    ua = headers.get("User-Agent", "")
    if "Firefox" in ua:
        browser = "firefox"
    elif "Edg" in ua:
        browser = "edge"
    elif "Chrome" in ua:
        browser = "chrome"
    else:
        browser = "other"
    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex[:8]
        m.SESSIONS.labels(browser).inc()
    forwarded = headers.get("X-Forwarded-For", "")
    ip = (forwarded.split(",")[0].strip()
          or getattr(st.context, "ip_address", None)
          or "127.0.0.1")
    return st.session_state.session_id, ip, browser


def process_one(data, mode):
    """Caption one image and record all per-image metrics."""
    m.IMAGE_BYTES.labels(mode).observe(len(data))
    m.BYTES_UPLOADED.labels(mode).inc(len(data))
    try:
        r = caption_image(processor, model, data)
    except Exception as e:
        m.IMAGES_PROCESSED.labels(mode, "error").inc()
        m.ERRORS.labels(mode, type(e).__name__).inc()
        raise
    m.PREPROCESS_SECONDS.labels(mode).observe(r["preprocess_s"])
    m.INFERENCE_SECONDS.labels(mode).observe(r["inference_s"])
    m.IMAGE_TOTAL_SECONDS.labels(mode).observe(r["preprocess_s"] + r["inference_s"])
    m.IMAGE_MEGAPIXELS.labels(mode).observe(r["megapixels"])
    m.CAPTION_WORDS.labels(mode).observe(len(r["caption"].split()))
    m.TOKENS_GENERATED.labels(mode).inc(r["tokens"])
    m.IMAGES_PROCESSED.labels(mode, "success").inc()
    m.LAST_SUCCESS_TS.set_to_current_time()
    return r


def run_single(data, meta):
    sid, ip, browser = meta
    m.REQUESTS.labels("single", sid, ip, browser).inc()
    with m.ACTIVE_REQUESTS.labels("single").track_inprogress(), \
         m.REQUEST_SECONDS.labels("single").time():
        try:
            r = process_one(data, "single")
            st.session_state.single_result = {"image": data, **r}
        except Exception as e:
            st.session_state.single_result = {"error": f"{type(e).__name__}: {e}"}


def select_images(zf):
    """Pick valid image entries from the ZIP; count everything skipped."""
    names = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        base = info.filename.rsplit("/", 1)[-1]
        if info.filename.startswith("__MACOSX/") or base.startswith("."):
            m.BULK_FILES_SKIPPED.labels("hidden_or_system").inc()
        elif not base.lower().endswith(IMG_EXT):
            m.BULK_FILES_SKIPPED.labels("not_an_image").inc()
        elif info.file_size > MAX_IMAGE_MB * 1024 * 1024:
            m.BULK_FILES_SKIPPED.labels("too_large").inc()
        else:
            names.append(info.filename)
    if len(names) > MAX_IMAGES_PER_ZIP:
        m.BULK_FILES_SKIPPED.labels("over_limit").inc(len(names) - MAX_IMAGES_PER_ZIP)
        names = names[:MAX_IMAGES_PER_ZIP]
    return names


def run_bulk(data, meta):
    sid, ip, browser = meta
    m.REQUESTS.labels("bulk", sid, ip, browser).inc()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        m.ERRORS.labels("bulk", "BadZipFile").inc()
        m.BULK_ZIPS.labels("rejected").inc()
        st.session_state.bulk_error = "That file is not a valid ZIP archive."
        return
    names = select_images(zf)
    if not names:
        m.BULK_ZIPS.labels("rejected").inc()
        st.session_state.bulk_error = "No supported images found in the ZIP."
        return

    m.LAST_BATCH_SIZE.set(len(names))
    m.BULK_BATCH_IMAGES.observe(len(names))
    results = []
    progress = st.progress(0.0, text="Starting...")
    with m.ACTIVE_REQUESTS.labels("bulk").track_inprogress(), \
         m.REQUEST_SECONDS.labels("bulk").time():
        try:
            for i, name in enumerate(names):
                m.BULK_QUEUE.set(len(names) - i)
                try:
                    r = process_one(zf.read(name), "bulk")
                    results.append({"file": name, "caption": r["caption"],
                                    "inference_s": round(r["inference_s"], 2), "status": "ok"})
                except Exception as e:
                    results.append({"file": name, "caption": "", "inference_s": None,
                                    "status": f"error: {type(e).__name__}"})
                progress.progress((i + 1) / len(names),
                                  text=f"Captioned {i + 1}/{len(names)}: {name}")
        finally:
            m.BULK_QUEUE.set(0)
    m.BULK_ZIPS.labels("completed").inc()
    st.session_state.bulk_results = results


# ---------------- UI ----------------
meta = client_meta()
st.title("🖼️ CPU Image Captioning")
st.caption(f"Model: `{MODEL_NAME}` on CPU · Metrics: http://localhost:{m.METRICS_PORT}/metrics")

with st.sidebar:
    st.subheader("Client metadata")
    st.write(f"Session ID: `{meta[0]}`")
    st.write(f"Client IP: `{meta[1]}`")
    st.write(f"Browser: `{meta[2]}`")
    st.caption("These are attached as labels on caption_requests_total.")

tab_single, tab_bulk = st.tabs(["Single image", "Bulk (ZIP)"])

with tab_single:
    up = st.file_uploader("Upload an image", type=[e.strip(".") for e in IMG_EXT],
                          key="single_upload")
    if up is not None and st.button("Generate caption", type="primary"):
        with st.spinner("Captioning..."):
            run_single(up.getvalue(), meta)
    res = st.session_state.get("single_result")
    if res:
        if "error" in res:
            st.error(f"Could not caption this image ({res['error']}).")
        else:
            c1, c2 = st.columns(2)
            c1.image(res["image"], width=420)
            c2.markdown(f"### “{res['caption']}”")
            c2.metric("Inference time", f"{res['inference_s']:.2f} s")
            c2.metric("Preprocess time", f"{res['preprocess_s']:.3f} s")
            c2.write(f"Original size: {res['megapixels']:.2f} MP · Tokens: {res['tokens']}")

with tab_bulk:
    st.write(f"Up to {MAX_IMAGES_PER_ZIP} images per ZIP ({', '.join(IMG_EXT)}). "
             "Other files are skipped.")
    zup = st.file_uploader("Upload a ZIP of images", type=["zip"], key="bulk_upload")
    if zup is not None and st.button("Caption all images", type="primary"):
        st.session_state.pop("bulk_error", None)
        st.session_state.pop("bulk_results", None)
        run_bulk(zup.getvalue(), meta)
    if st.session_state.get("bulk_error"):
        st.error(st.session_state.bulk_error)
    results = st.session_state.get("bulk_results")
    if results:
        df = pd.DataFrame(results)
        ok = int((df["status"] == "ok").sum())
        st.success(f"Captioned {ok}/{len(df)} images.")
        st.dataframe(df, hide_index=True)
        st.download_button("Download captions (CSV)", df.to_csv(index=False),
                           "captions.csv", "text/csv")
