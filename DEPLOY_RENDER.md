# Deploy TA-MSD Viewer on Render

This folder is a self-contained Flask app for Render. It expects the generated data under:

```text
plots/Spike/<country>/
  ta_msd_regressions.json
  ta_msd_plot_data.json
```

## Files to include

- `app.py`
- `requirements.txt`
- `Procfile`
- `render.yaml`
- `plots/Spike/...` generated JSON data

## Render Dashboard Settings

Create a Web Service and point Render at this folder.

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120 app:app` |
| Health check path | `/healthz` |

If the repository root is higher than this folder, set Render's root directory to:

```text
publish/webapp
```

## Data Path Override

By default the app loads data from `plots/Spike` inside this folder. To use a different path, set:

```text
TA_MSD_PLOTS_ROOT=/path/to/plots/Spike
```

Relative paths are resolved from this `webapp` directory.

## Local Run

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`.
