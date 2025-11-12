import json
import os
import time
from statistics import mean

import streamlit as st
import requests

# Auto-load .env when present (optional). This is non-fatal if python-dotenv is not installed.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# Show title and description.
st.title(" Localdev assistant ")
st.set_page_config(page_title="Chatbot", layout="wide")

# Apply a minimal dark theme (black background, light text) to resemble a Vercel-like dark UI.
st.markdown(
        """
        <style>
            /* Page background and main container */
            .reportview-container, .main, .block-container {
                background: #000000;
                color: #e6eef6;
            }
            /* Chat bubbles and cards */
            .stChatMessage, .stMarkdown, .stButton>button {
                color: #e6eef6;
            }
            /* Make assistant messages slightly lighter */
            .assistant { color: #f1f5f9; }
            .user { color: #cbd5e1; }
            a { color: #7dd3fc; }
        </style>
        """,
        unsafe_allow_html=True,
)

# Helper: extract text from various JSON shapes returned by inference endpoints

def extract_text_from_json(data):
    # Strings
    if isinstance(data, str):
        return data
    # Dicts
    if isinstance(data, dict):
        # common single-field text keys
        for key in ("text", "output", "result", "response", "completion"):
            if key in data and isinstance(data[key], str):
                return data[key]

        # OpenAI-like choices
        if "choices" in data and isinstance(data["choices"], list):
            texts = []
            for c in data["choices"]:
                if isinstance(c, dict):
                    if "message" in c and isinstance(c["message"], dict):
                        msg = c["message"].get("content")
                        if msg:
                            texts.append(msg)
                    elif "text" in c and isinstance(c["text"], str):
                        texts.append(c["text"])
            return "\n".join(texts).strip()

        # Ollama-like completions
        if "completions" in data and isinstance(data["completions"], list):
            texts = []
            for c in data["completions"]:
                if isinstance(c, dict):
                    for k in ("data", "content", "text", "output"):
                        if k in c:
                            v = c[k]
                            if isinstance(v, str):
                                texts.append(v)
                            elif isinstance(v, list):
                                texts.extend([str(i) for i in v])
            return "\n".join(texts).strip()

        # If none matched, stringify
        try:
            return json.dumps(data)
        except Exception:
            return str(data)

    # Lists
    if isinstance(data, list):
        return "\n".join(filter(None, (extract_text_from_json(i) for i in data)))

    return str(data)


@st.cache_data(ttl=3600)
def query_ollama_cached(prompt: str, model: str, n_predict: int, endpoint: str):
    headers = {"Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "n_predict": int(n_predict), "stream": False}
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")
    body = None
    content = None
    if "application/json" in ctype:
        try:
            body = resp.json()
            content = extract_text_from_json(body)
        except Exception:
            content = resp.text
    else:
        content = resp.text

    return {"content": content, "body": body, "headers": dict(resp.headers)}

st.write(
    "This is a simple chatbot that uses a locally hosted Ollama Mistral model exposed via an HTTP endpoint. The endpoint is read from environment or Streamlit secrets (not shown in the UI)."
)

# Obtain endpoint from environment or Streamlit secrets (hidden from UI)
endpoint = os.environ.get("OLLAMA_ENDPOINT")
if not endpoint:
    # Access Streamlit secrets safely; `st.secrets` may raise if no secrets file is present.
    try:
        endpoint = st.secrets["ollama_endpoint"]
    except Exception:
        endpoint = None

# Optional model and generation settings
model = st.text_input("Model", value="mistral")
n_predict = st.number_input("n_predict", min_value=1, max_value=2048, value=50)

# LangSmith settings (optional)
LANGSMITH_API_KEY = os.environ.get("LANGSMITH_API_KEY")
LANGSMITH_URL = os.environ.get("LANGSMITH_URL", "https://api.langsmith.ai/v1/runs")

# Show app URL if provided via environment (VERCEL_URL or APP_URL)
app_url = os.environ.get("APP_URL") or os.environ.get("VERCEL_URL")
if app_url:
    # Vercel sets VERCEL_URL without scheme, so add https:// if missing
    if not app_url.startswith("http"):
        app_url = f"https://{app_url}"
    st.caption(f"Running at: {app_url}")

if not endpoint:
    st.error("Ollama endpoint not configured. Set the OLLAMA_ENDPOINT environment variable or add `ollama_endpoint` to Streamlit secrets.")
else:

    # Create a session state variable to store the chat messages. This ensures that the
    # messages persist across reruns.
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Analytics toggle and storage in session state
    enable_analytics = st.checkbox("Enable analytics (latency & inference time)", value=True)
    send_langsmith = st.checkbox("Send logs to LangSmith", value=bool(LANGSMITH_API_KEY))
    if "analytics" not in st.session_state:
        st.session_state.analytics = {
            "records": [],  # list of {timestamp, latency, inference_time, network_time}
        }


# Cached query function: caches response content+body+headers for identical prompts/settings
    # Display the existing chat messages via `st.chat_message`.
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            # show per-message timing if present
            meta = message.get("meta")
            if meta and enable_analytics:
                it = meta.get("inference_time")
                lt = meta.get("latency")
                net = meta.get("network_time")
                parts = []
                if it is not None:
                    parts.append(f"inference: {it:.3f}s")
                if lt is not None:
                    parts.append(f"rtt: {lt:.3f}s")
                if net is not None:
                    parts.append(f"network: {net:.3f}s")
                if parts:
                    st.caption(" • ".join(parts))

    # Create a chat input field to allow the user to enter a message. This will display
    # automatically at the bottom of the page.
    if prompt := st.chat_input("What is up?"):

        # Store and display the current prompt.
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Store and display the current prompt (user message already added above).

        # Build a prompt for the remote model. We include conversation history to
        # provide context. Many local inference endpoints accept a plain prompt
        # string; we concatenate roles to keep context simple.
        prompt_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in st.session_state.messages
        )

        # Prepare request payload for the Ollama /api/generate endpoint
        payload = {
            "model": model,
            "prompt": prompt_text,
            "n_predict": int(n_predict),
            "stream": False,
        }

        headers = {"Content-Type": "application/json"}

        # Use cached query helper to call the Ollama endpoint (cached by prompt/model/n_predict)
        start_t = time.time()
        try:
            result = query_ollama_cached(prompt_text, model, n_predict, endpoint)
            latency = time.time() - start_t
            content = result.get("content")
            body = result.get("body")
            resp_headers = result.get("headers") or {}
        except Exception as e:
            with st.chat_message("assistant"):
                st.markdown(f"**Error contacting model endpoint:** {e}")
            st.session_state.messages.append({"role": "assistant", "content": f"Error: {e}"})
            # record the failed attempt in analytics
            st.session_state.analytics.setdefault("records", []).append({"timestamp": time.time(), "error": str(e)})
            st.stop()

        # derive inference time if returned by the model
        def find_inference_time(body_obj, headers=None):
            # Check headers first for common timing headers
            if headers:
                for hk in ("x-inference-time", "x-process-time", "x-runtime-ms", "x-duration-ms"):
                    hv = headers.get(hk)
                    if hv:
                        try:
                            # some headers are in ms
                            v = float(hv)
                            # normalize ms to seconds if value looks large
                            if v > 10:
                                return v / 1000.0
                            return v
                        except Exception:
                            pass

            # Search JSON body for common keys
            def _search(d):
                if d is None:
                    return None
                if isinstance(d, dict):
                    for key in ("inference_time", "inferenceSeconds", "duration", "elapsed", "time", "runtime"):
                        if key in d:
                            try:
                                return float(d[key])
                            except Exception:
                                pass
                    # nested search
                    for v in d.values():
                        res = _search(v)
                        if res is not None:
                            return res
                if isinstance(d, list):
                    for i in d:
                        res = _search(i)
                        if res is not None:
                            return res
                return None

            t = _search(body_obj)
            # if t looks like milliseconds (large), normalize
            if t is not None and t > 10:
                t = t / 1000.0
            return t

        inference_time = None
        if enable_analytics:
            inference_time = find_inference_time(body, headers=resp_headers)

        network_time = latency
        if inference_time is not None:
            # network time is the remainder
            network_time = max(latency - inference_time, 0.0)

        # record analytics
        if enable_analytics:
            st.session_state.analytics.setdefault("records", []).append(
                {
                    "timestamp": time.time(),
                    "latency": latency,
                    "inference_time": inference_time,
                    "network_time": network_time,
                }
            )

        # (LangSmith logging moved below, after we extract content)

        with st.chat_message("assistant"):
            st.markdown(content)
            # display timing inline for this assistant message
            if enable_analytics:
                parts = []
                if inference_time is not None:
                    parts.append(f"inference: {inference_time:.3f}s")
                parts.append(f"rtt: {latency:.3f}s")
                st.caption(" • ".join(parts))

        st.session_state.messages.append({"role": "assistant", "content": content, "meta": {"latency": latency, "inference_time": inference_time, "network_time": network_time}})

        # Optionally send a log to LangSmith (non-blocking) -- do this after we have `content`.
        if send_langsmith and LANGSMITH_API_KEY:
            try:
                ls_headers = {"Authorization": f"Bearer {LANGSMITH_API_KEY}", "Content-Type": "application/json"}
                ls_payload = {
                    "name": "streamlit-chat-run",
                    "project": os.environ.get("LANGSMITH_PROJECT"),
                    "inputs": {
                        "prompt": prompt_text,
                        "model": model,
                        "n_predict": int(n_predict),
                    },
                    "outputs": {"text": content},
                    "metrics": {
                        "latency": latency,
                        "inference_time": inference_time,
                        "network_time": network_time,
                    },
                    "tags": ["streamlit", "ollama"],
                    "metadata": {"app_url": app_url},
                }
                # fire-and-forget but do it synchronously with a short timeout; failures are ignored
                try:
                    ls_resp = requests.post(LANGSMITH_URL, json=ls_payload, headers=ls_headers, timeout=5)
                    # don't raise for non-2xx, just log the status in the session analytics
                    st.session_state.analytics.setdefault("langsmith", []).append({
                        "time": time.time(),
                        "status_code": ls_resp.status_code,
                        "ok": ls_resp.ok,
                    })
                except Exception as _e:
                    st.session_state.analytics.setdefault("langsmith", []).append({"time": time.time(), "error": str(_e)})
            except Exception:
                # ensure LangSmith logging never breaks the app
                pass

        # --- Analytics UI (small panel) ---
        with st.expander("Analytics: throughput, latency & inference time", expanded=False):
            a = st.session_state.analytics
            # Rolling time windows
            now = time.time()
            # Keep only last 6 hours to bound memory
            cutoff = now - 60 * 60 * 6
            a["records"] = [r for r in a["records"] if r["timestamp"] >= cutoff]

            total_requests = len(a["records"])
            latencies = [r["latency"] for r in a["records"] if r.get("latency") is not None]
            inference_times = [r["inference_time"] for r in a["records"] if r.get("inference_time") is not None]
            network_times = [r["network_time"] for r in a["records"] if r.get("network_time") is not None]

            last_latency = latencies[-1] if latencies else None
            avg_latency = mean(latencies) if latencies else None
            avg_inference = mean(inference_times) if inference_times else None
            avg_network = mean(network_times) if network_times else None

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total requests", total_requests)
            col2.metric("Last latency (s)", f"{last_latency:.3f}" if last_latency else "—")
            col3.metric("Avg latency (s)", f"{avg_latency:.3f}" if avg_latency else "—")
            col4.metric("Avg inference (s)", f"{avg_inference:.3f}" if avg_inference else "—")

            # Throughput: compute requests per minute over the last 1 and 5 minutes
            def rpm(window_seconds: int):
                cutoff_w = now - window_seconds
                return sum(1 for r in a["records"] if r["timestamp"] >= cutoff_w) / (window_seconds / 60)

            r1 = rpm(60)
            r5 = rpm(300)
            st.write(f"Throughput: {r1:.2f} req/min (1m), {r5:.2f} req/min (5m)")

            if latencies:
                st.line_chart(latencies[-200:])
            if inference_times:
                st.line_chart(inference_times[-200:])

            if st.button("Reset analytics"):
                st.session_state.analytics = {"records": []}
