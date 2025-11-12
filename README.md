# 💬 Chatbot template

A simple Streamlit app that shows how to build a chatbot using OpenAI's GPT-3.5.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://chatbot-template.streamlit.app/)

### How to run it on your own machine

1. Install the requirements

   ```
   $ pip install -r requirements.txt
   ```

2. Run the app

   ```
   $ streamlit run streamlit_app.py
   ```

Notes on using a local Ollama model via ngrok
-------------------------------------------

This Streamlit app can use a locally hosted Ollama model exposed via an HTTP endpoint (for example using ngrok). The app comes pre-filled with an example ngrok URL; you can replace it in the UI.

Quick steps:

- Run your Ollama server locally (example):

   ```bash
   ollama serve
   ```

- Expose the local port (default Ollama port 11434) with ngrok:

   ```bash
   ngrok http 11434 --host-header="localhost:11434"
   ```

- Copy the generated ngrok HTTPS URL and paste it into the "Ollama endpoint URL" field in the Streamlit app. The app expects the full path to the generate endpoint, for example:

   ```text
   https://<your-ngrok-subdomain>.ngrok-free.dev/api/generate
   ```

The app sends POST requests with JSON like:

```json
{
   "model": "mistral",
   "prompt": "<your conversation text>",
   "n_predict": 50,
   "stream": false
}
```

Make sure your local Ollama instance and ngrok tunnel are running before sending prompts.

Configuration for deployment
----------------------------

When deploying this app (for example to Vercel or similar), do not expose your Ollama endpoint in the UI. Instead set an environment variable named `OLLAMA_ENDPOINT` to the full generate URL, for example:

```
OLLAMA_ENDPOINT=https://flowered-melania-stagiest.ngrok-free.dev/api/generate
```

If you want the app to show its public URL, set `APP_URL` (or your platform's `VERCEL_URL`) in the deployment env variables. The app will display that URL in the UI under "Running at:".

Analytics
---------

The Streamlit app includes a lightweight analytics panel (local to each session) that tracks:

- total requests made from the session
- last request latency (seconds)
- average latency (seconds)
- throughput (requests per minute over 1m and 5m windows)

These analytics are stored in-session only (in memory). For production monitoring across users you should wire analytics to an external store (InfluxDB, Prometheus, or a logging/metrics backend) and export metrics there.
