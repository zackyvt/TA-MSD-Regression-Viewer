from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from flask import Flask, abort, jsonify, render_template_string, request


BASE_DIR = Path(__file__).resolve().parent
PUBLISH_DIR = BASE_DIR.parent
JSON_NAME = "ta_msd_regressions.json"
PLOT_DATA_JSON_NAME = "ta_msd_plot_data.json"
DEFAULT_WEBAPP_PLOTS_ROOT = BASE_DIR / "plots" / "Spike"
DEFAULT_PUBLISH_PLOTS_ROOT = PUBLISH_DIR / "plots" / "Spike"
INTERVAL_BROWSER_DEFAULT_PAGE_SIZE = 24
INTERVAL_BROWSER_MAX_PAGE_SIZE = 96

app = Flask(__name__)


def _plots_root() -> Path:
    override = os.environ.get("TA_MSD_PLOTS_ROOT", "").strip()
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path
    if DEFAULT_WEBAPP_PLOTS_ROOT.is_dir():
        return DEFAULT_WEBAPP_PLOTS_ROOT
    return DEFAULT_PUBLISH_PLOTS_ROOT


@lru_cache(maxsize=1)
def _available_countries() -> list[str]:
    plots_root = _plots_root()
    if not plots_root.is_dir():
        raise FileNotFoundError(f"Could not find plots directory: {plots_root}")
    countries = [
        path.name
        for path in plots_root.iterdir()
        if path.is_dir() and (path / JSON_NAME).is_file() and (path / PLOT_DATA_JSON_NAME).is_file()
    ]
    if not countries:
        raise FileNotFoundError(
            f"No country directories with {JSON_NAME} and {PLOT_DATA_JSON_NAME} found in {plots_root}"
        )
    return sorted(countries, key=lambda c: (c != "all", c.casefold()))


def _resolve_data_dir(country: str) -> Path:
    countries = _available_countries()
    if country not in countries:
        raise FileNotFoundError(f"Country/region {country!r} was not found in {_plots_root()}")

    data_dir = _plots_root() / country
    if not (data_dir / JSON_NAME).is_file():
        raise FileNotFoundError(f"{JSON_NAME} was not found in {data_dir}")
    if not (data_dir / PLOT_DATA_JSON_NAME).is_file():
        raise FileNotFoundError(f"{PLOT_DATA_JSON_NAME} was not found in {data_dir}")
    return data_dir


@lru_cache(maxsize=64)
def _load_data(country: str) -> tuple[Path, dict]:
    data_dir = _resolve_data_dir(country)
    with (data_dir / JSON_NAME).open("r", encoding="utf-8") as f:
        return data_dir, json.load(f)


@lru_cache(maxsize=64)
def _load_plot_data(country: str) -> dict:
    data_dir = _resolve_data_dir(country)
    with (data_dir / PLOT_DATA_JSON_NAME).open("r", encoding="utf-8") as f:
        return json.load(f)


def _site_sort_key(site: str):
    try:
        return (0, int(site))
    except ValueError:
        return (1, site)


def _format_ci(low, high) -> str:
    if low is None or high is None:
        return "-"
    return f"[{low:.6g}, {high:.6g}]"


def _format_number(value) -> str:
    if value is None:
        return "-"
    return f"{value:.6g}"


ALPHA_FILTERS = [
    ("any", "Any alpha label"),
    ("superdiffusive", "Superdiffusive"),
    ("subdiffusive", "Subdiffusive"),
    ("brownian", "Brownian consistent"),
    ("quiescent", "Quiescent"),
    ("inconclusive", "Inconclusive"),
]

WF_R2_FILTERS = [
    ("any", "Any WF R²"),
    ("lt_0_2", "< 0.2"),
    ("0_2_0_5", "0.2 - 0.5"),
    ("0_5_0_7", "0.5 - 0.7"),
    ("0_7_0_9", "0.7 - 0.9"),
    ("gt_0_9", "> 0.9"),
]

RESIDUAL_ALPHA_FILTERS = [
    ("any", "Any residual alpha"),
    ("subdiffusive", "Subdiffusive"),
    ("brownian", "Brownian consistent"),
    ("superdiffusive", "Superdiffusive"),
]


def _normalize_diffusion_label(label) -> str:
    normalized = str(label or "").strip().casefold()
    if normalized in {"brownian-consistent", "brownian consistent", "brownian"}:
        return "brownian"
    if normalized in {"superdiffusive", "subdiffusive", "inconclusive", "quiescent"}:
        return normalized
    return normalized or "unknown"


def _interval_alpha_category(interval: dict) -> str:
    phase_label = str(interval.get("phase_label") or "").casefold()
    if phase_label == "quiescent":
        return "quiescent"
    return _normalize_diffusion_label(interval.get("diffusion_label"))


def _wf_r2_matches(value, selected_filter: str) -> bool:
    if selected_filter == "any":
        return True
    if value is None:
        return False
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    if selected_filter == "lt_0_2":
        return value < 0.2
    if selected_filter == "0_2_0_5":
        return 0.2 <= value < 0.5
    if selected_filter == "0_5_0_7":
        return 0.5 <= value < 0.7
    if selected_filter == "0_7_0_9":
        return 0.7 <= value < 0.9
    if selected_filter == "gt_0_9":
        return value >= 0.9
    return True


def _series_summary(series: dict) -> dict:
    return {
        "label": series.get("label"),
        "dates": series.get("dates", []),
        "date_labels": series.get("date_labels", []),
        "mutant_freq": series.get("mutant_freq", []),
        "wf_fitted_mean": series.get("wf_fitted_mean", []),
    }


def _browse_interval_cards(
    alpha_filter: str,
    wf_r2_filter: str,
    residual_alpha_filter: str,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[dict], int]:
    cards = []
    total_matches = 0
    for country in _available_countries():
        _, regression_data = _load_data(country)
        plot_data = None
        for site in sorted(regression_data.get("sites", {}).keys(), key=_site_sort_key):
            intervals = regression_data.get("sites", {}).get(site, {}).get("intervals", [])
            for interval_index, interval in enumerate(intervals):
                alpha_category = _interval_alpha_category(interval)
                residual_category = _normalize_diffusion_label(interval.get("residual_diffusion_label"))
                if alpha_filter != "any" and alpha_category != alpha_filter:
                    continue
                if not _wf_r2_matches(interval.get("wf_r_squared"), wf_r2_filter):
                    continue
                if residual_alpha_filter != "any" and residual_category != residual_alpha_filter:
                    continue

                total_matches += 1
                if total_matches <= offset:
                    continue
                if limit is not None and len(cards) >= limit:
                    continue

                if plot_data is None:
                    plot_data = _load_plot_data(country)
                series_list = plot_data.get("sites", {}).get(site, {}).get("series", [])
                series = series_list[interval_index] if interval_index < len(series_list) else {}
                cards.append({
                    "country": country,
                    "site": site,
                    "interval_index": interval_index,
                    "label": interval.get("label", ""),
                    "phase_label": interval.get("phase_label", "active"),
                    "alpha_label": alpha_category,
                    "residual_alpha_label": residual_category,
                    "wf_r_squared": interval.get("wf_r_squared"),
                    "wf_selection_coefficient": interval.get("wf_selection_coefficient"),
                    "alpha": interval.get("slope"),
                    "residual_alpha": interval.get("residual_slope"),
                    "start_date": interval.get("start_date"),
                    "end_date": interval.get("end_date"),
                    "series": _series_summary(series),
                })
    return cards, total_matches


def _parse_positive_int(value, default, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(parsed, 1)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


@app.route("/")
def index():
    try:
        countries = _available_countries()
        selected_country = request.args.get("country") or countries[0]
        if selected_country not in countries:
            selected_country = countries[0]
        data_dir, data = _load_data(selected_country)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return render_template_string(ERROR_TEMPLATE, error=str(exc)), 500

    sites = sorted(data.get("sites", {}).keys(), key=_site_sort_key)
    selected_site = request.args.get("site") or (sites[0] if sites else None)
    if selected_site not in data.get("sites", {}):
        selected_site = sites[0] if sites else None

    site_data = data.get("sites", {}).get(selected_site, {}) if selected_site else {}
    return render_template_string(
        PAGE_TEMPLATE,
        data=data,
        data_dir=data_dir,
        countries=countries,
        selected_country=selected_country,
        sites=sites,
        selected_site=selected_site,
        site_data=site_data,
        format_ci=_format_ci,
        format_number=_format_number,
    )


@app.route("/intervals")
def interval_browser():
    try:
        countries = _available_countries()
        alpha_filter = request.args.get("alpha", "any")
        wf_r2_filter = request.args.get("wf_r2", "any")
        residual_alpha_filter = request.args.get("residual_alpha", "any")
        if alpha_filter not in dict(ALPHA_FILTERS):
            alpha_filter = "any"
        if wf_r2_filter not in dict(WF_R2_FILTERS):
            wf_r2_filter = "any"
        if residual_alpha_filter not in dict(RESIDUAL_ALPHA_FILTERS):
            residual_alpha_filter = "any"
        page_size = _parse_positive_int(
            request.args.get("page_size"),
            INTERVAL_BROWSER_DEFAULT_PAGE_SIZE,
            INTERVAL_BROWSER_MAX_PAGE_SIZE,
        )
        page = _parse_positive_int(request.args.get("page"), 1)
        page = _parse_positive_int(request.args.get("page"), 1)
        start = (page - 1) * page_size
        cards, total_cards = _browse_interval_cards(
            alpha_filter,
            wf_r2_filter,
            residual_alpha_filter,
            offset=start,
            limit=page_size,
        )
        total_pages = max((total_cards + page_size - 1) // page_size, 1)
        if page > total_pages:
            page = total_pages
            start = (page - 1) * page_size
            cards, total_cards = _browse_interval_cards(
                alpha_filter,
                wf_r2_filter,
                residual_alpha_filter,
                offset=start,
                limit=page_size,
            )
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return render_template_string(ERROR_TEMPLATE, error=str(exc)), 500

    return render_template_string(
        INTERVAL_BROWSER_TEMPLATE,
        countries=countries,
        cards=cards,
        alpha_filters=ALPHA_FILTERS,
        wf_r2_filters=WF_R2_FILTERS,
        residual_alpha_filters=RESIDUAL_ALPHA_FILTERS,
        selected_alpha=alpha_filter,
        selected_wf_r2=wf_r2_filter,
        selected_residual_alpha=residual_alpha_filter,
        page=page,
        page_size=page_size,
        total_cards=total_cards,
        total_pages=total_pages,
        format_number=_format_number,
    )


@app.route("/plot-data/<country>/<site>")
def plot_data(country: str, site: str):
    try:
        data = _load_plot_data(country)
    except (FileNotFoundError, json.JSONDecodeError):
        abort(404)

    site_data = data.get("sites", {}).get(site)
    if not site_data:
        abort(404)
    return jsonify(site_data)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TA MSD Regression Viewer</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Arial, Helvetica, sans-serif;
      color: #1f2937;
      background: #f3f4f6;
    }
    body {
      margin: 0;
      padding: 32px;
    }
    main {
      max-width: 1180px;
      margin: 0 auto;
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
      padding: 28px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 28px;
    }
    .meta {
      margin: 0 0 22px;
      color: #6b7280;
      font-size: 14px;
    }
    .nav {
      display: flex;
      gap: 14px;
      margin: 0 0 22px;
      font-size: 14px;
    }
    .nav a {
      color: #2563eb;
      font-weight: 700;
      text-decoration: none;
    }
    .nav a:hover {
      text-decoration: underline;
    }
    form {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 24px;
    }
    label {
      font-weight: 700;
    }
    select {
      min-width: 180px;
      padding: 8px 10px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      font-size: 15px;
    }
    .plot-container {
      width: 100%;
      min-height: 420px;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      background: #fff;
      overflow-x: auto;
      margin-top: 20px;
    }
    .plot-container svg {
      display: block;
      width: 100%;
      min-width: 840px;
    }
    .plot-message {
      padding: 24px;
      color: #6b7280;
    }
    .plot-controls {
      display: flex;
      flex-wrap: wrap;
      gap: 12px 18px;
      align-items: center;
      margin: 18px 0 0;
      padding: 12px;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      background: #f8fafc;
    }
    .plot-controls label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-weight: 700;
    }
    .plot-controls input[type="checkbox"] {
      width: 16px;
      height: 16px;
    }
    table {
      width: 100%;
      margin-bottom: 24px;
      border-collapse: collapse;
      font-size: 14px;
    }
    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      white-space: nowrap;
    }
    th {
      background: #f8fafc;
      color: #374151;
    }
    tr.interval-row {
      cursor: pointer;
    }
    tr.interval-row:hover {
      background: #f8fafc;
    }
    .empty {
      padding: 24px;
      border: 1px dashed #cbd5e1;
      border-radius: 10px;
      color: #6b7280;
    }
  </style>
</head>
<body>
  <main>
    <h1>TA MSD Regression Viewer</h1>
    <p class="meta">
      Protein: {{ data.get("protein", "unknown") }} |
      Country/region: {{ data.get("country", "unknown") }} |
    </p>
    <nav class="nav">
      <a href="{{ url_for('index', country=selected_country, site=selected_site) }}">Site viewer</a>
      <a href="{{ url_for('interval_browser') }}">Browse intervals</a>
    </nav>

    {% if selected_site %}
      <form method="get">
        <label for="country">Country/region</label>
        <select id="country" name="country" onchange="this.form.submit()">
          {% for country in countries %}
            <option value="{{ country }}" {% if country == selected_country %}selected{% endif %}>{{ country }}</option>
          {% endfor %}
        </select>

        <label for="site">Site</label>
        <select id="site" name="site" onchange="this.form.submit()">
          {% for site in sites %}
            <option value="{{ site }}" {% if site == selected_site %}selected{% endif %}>{{ site }}</option>
          {% endfor %}
        </select>
      </form>

            <table>
        <thead>
          <tr>
            <th>Interval</th>
            <th>Phase</th>
            <th>Consensus base</th>
            <th>Mutant base</th>
            <th>Start</th>
            <th>End</th>
            <th>Alpha coefficient</th>
            <th>Alpha 95% CI</th>
            <th>R²</th>
            <th>WF s / day</th>
            <th>WF 95% CI</th>
            <th>WF R²</th>
            <th>Residual alpha</th>
            <th>Residual alpha 95% CI</th>
            <th>Residual R²</th>
            <th>Diffusion type</th>
            <th>Days</th>
          </tr>
        </thead>
        <tbody>
          {% for interval in site_data.get("intervals", []) %}
            <tr class="interval-row" data-interval-index="{{ loop.index0 }}">
              <td>{{ interval.label }}</td>
              <td>{{ interval.get("phase_label", "active") }}</td>
              <td>{{ interval.get("most_common_aa") or "-" }}</td>
              <td>{{ interval.get("second_most_common_aa") or "-" }}</td>
              <td>{{ interval.start_date }} ({{ interval.start }})</td>
              <td>{{ interval.end_date }} ({{ interval.end }})</td>
              <td>{{ format_number(interval.get("slope")) }}</td>
              <td>{{ format_ci(interval.get("alpha_ci_low"), interval.get("alpha_ci_high")) }}</td>
              <td>{{ format_number(interval.get("r_squared")) }}</td>
              <td>{{ format_number(interval.get("wf_selection_coefficient")) }}</td>
              <td>{{ format_ci(interval.get("wf_selection_ci_low"), interval.get("wf_selection_ci_high")) }}</td>
              <td>{{ format_number(interval.get("wf_r_squared")) }}</td>
              <td>{{ format_number(interval.get("residual_slope")) }}</td>
              <td>{{ format_ci(interval.get("residual_alpha_ci_low"), interval.get("residual_alpha_ci_high")) }}</td>
              <td>{{ format_number(interval.get("residual_r_squared")) }}</td>
              <td>{{ interval.get("diffusion_label", "uncertain") }}</td>
              <td>{{ interval.n_points }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>

      <div id="plot-controls" class="plot-controls" hidden>
        <label for="interval-focus">Focus interval</label>
        <select id="interval-focus">
          <option value="all">All intervals</option>
        </select>
        <label style="display: none">
          <input id="show-frequency-panels" type="checkbox" checked>
          Show frequency panels
        </label>
      </div>

      <div id="plot-container" class="plot-container">
        <div class="plot-message">Loading plot data...</div>
      </div>

      <script>
        const plotDataUrl = "{{ url_for('plot_data', country=selected_country, site=selected_site) }}";
        const plotContainer = document.getElementById("plot-container");
        const plotControls = document.getElementById("plot-controls");
        const intervalFocus = document.getElementById("interval-focus");
        const showFrequencyPanels = document.getElementById("show-frequency-panels");
        const colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];

        function svgEl(name, attrs = {}) {
          const el = document.createElementNS("http://www.w3.org/2000/svg", name);
          for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
          }
          return el;
        }

        function log10(value) {
          return Math.log(value) / Math.LN10;
        }

        function linspace(start, end, count) {
          if (count <= 1) return [start];
          const step = (end - start) / (count - 1);
          return Array.from({ length: count }, (_, i) => start + i * step);
        }

        function pathFromPoints(points) {
          return points.map((point, i) => `${i === 0 ? "M" : "L"}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(" ");
        }

        function addText(svg, text, x, y, attrs = {}) {
          const el = svgEl("text", { x, y, ...attrs });
          el.textContent = text;
          svg.appendChild(el);
          return el;
        }

        function drawAxes(svg, panel, xTicks, yTicks, xScale, yScale, xLabel, yLabel, xFormatter = formatTick, yFormatter = formatTick) {
          const { x, y, width, height } = panel;
          svg.appendChild(svgEl("rect", { x, y, width, height, fill: "#fff", stroke: "#d1d5db" }));

          for (const tick of xTicks) {
            const px = xScale(tick);
            svg.appendChild(svgEl("line", { x1: px, y1: y, x2: px, y2: y + height, stroke: "#e5e7eb", "stroke-dasharray": "4 4" }));
            addText(svg, xFormatter(tick), px, y + height + 18, { "text-anchor": "middle", "font-size": 11, fill: "#4b5563" });
          }

          for (const tick of yTicks) {
            const py = yScale(tick);
            svg.appendChild(svgEl("line", { x1: x, y1: py, x2: x + width, y2: py, stroke: "#e5e7eb", "stroke-dasharray": "4 4" }));
            addText(svg, yFormatter(tick), x - 10, py + 4, { "text-anchor": "end", "font-size": 11, fill: "#4b5563" });
          }

          addText(svg, xLabel, x + width / 2, y + height + 44, { "text-anchor": "middle", "font-size": 13, "font-weight": 600, fill: "#1f2937" });
          const yAxisLabel = addText(svg, yLabel, x - 54, y + height / 2, { "text-anchor": "middle", "font-size": 13, "font-weight": 600, fill: "#1f2937", transform: `rotate(-90 ${x - 54} ${y + height / 2})` });
          return yAxisLabel;
        }

        function formatTick(value) {
          if (value === 0) return "0";
          if (Math.abs(value) >= 1000 || Math.abs(value) < 0.01) return value.toExponential(1);
          if (Math.abs(value) < 1) return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
          return Math.round(value).toString();
        }

        function formatDateTick(days) {
          const base = new Date(Date.UTC(2019, 11, 31));
          base.setUTCDate(base.getUTCDate() + Math.round(days));
          return base.toLocaleDateString(undefined, { year: "numeric", month: "short" });
        }

        function logTicks(minValue, maxValue) {
          const lo = Math.floor(log10(minValue));
          const hi = Math.ceil(log10(maxValue));
          const ticks = [];
          for (let p = lo; p <= hi; p++) {
            const tick = Math.pow(10, p);
            if (tick >= minValue && tick <= maxValue) ticks.push(tick);
          }
          if (ticks.length < 2) {
            ticks.push(minValue, maxValue);
          }
          return [...new Set(ticks)];
        }

        function linearTicks(minValue, maxValue, count = 5) {
          return linspace(minValue, maxValue, count);
        }

        function seriesWithIndices(data) {
          return (data.series || []).map((s, index) => ({ ...s, _seriesIndex: index }));
        }

        function selectedSeries(data) {
          const series = seriesWithIndices(data);
          const selected = intervalFocus.value;
          if (selected === "all") return series;
          const selectedIndex = Number(selected);
          return series.filter(s => s._seriesIndex === selectedIndex);
        }

        function populatePlotControls(data) {
          const series = seriesWithIndices(data);
          intervalFocus.innerHTML = '<option value="all">All intervals</option>';
          series.forEach(s => {
            const option = document.createElement("option");
            option.value = String(s._seriesIndex);
            const status = s.phase_label === "quiescent" ? "quiescent" : (s.show_in_ta_msd_plot === false ? "inconclusive" : (s.diffusion_label || "unlabeled"));
            option.textContent = `${s.label} (${status})`;
            intervalFocus.appendChild(option);
          });
          plotControls.hidden = series.length === 0;
          intervalFocus.onchange = () => renderPlot(data);
          showFrequencyPanels.onchange = () => renderPlot(data);
          document.querySelectorAll(".interval-row").forEach(row => {
            row.onclick = () => {
              intervalFocus.value = row.dataset.intervalIndex;
              renderPlot(data);
              plotContainer.scrollIntoView({ behavior: "smooth", block: "start" });
            };
          });
        }

        function renderPlot(data) {
          const series = selectedSeries(data);
          if (series.length === 0) {
            plotContainer.innerHTML = '<div class="plot-message">No plot data found for this site.</div>';
            return;
          }
          const taMsdSeries = series.filter(s => s.show_in_ta_msd_plot !== false);
          const frequencySeries = showFrequencyPanels.checked ? series : [];

          const width = Math.max(plotContainer.clientWidth || 1000, 1000);
          const margin = { left: 82, right: 34 };
          const topPanelHeight = 330;
          const freqPanelHeight = 210;
          const panelGap = 78;
          const height = 64 + topPanelHeight + (frequencySeries.length > 0 ? panelGap : 40) + frequencySeries.length * (freqPanelHeight + panelGap);
          const plotWidth = width - margin.left - margin.right;
          const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": data.title || "TA MSD plot" });

          addText(svg, data.title || "TA MSD plot", width / 2, 28, { "text-anchor": "middle", "font-size": 18, "font-weight": 700, fill: "#111827" });

          const topPanel = { x: margin.left, y: 52, width: plotWidth, height: topPanelHeight };
          if (taMsdSeries.length === 0) {
            svg.appendChild(svgEl("rect", { x: topPanel.x, y: topPanel.y, width: topPanel.width, height: topPanel.height, fill: "#fff", stroke: "#d1d5db" }));
            addText(svg, "No intervals meet the TA-MSD plot R² cutoff.", topPanel.x + topPanel.width / 2, topPanel.y + topPanel.height / 2, { "text-anchor": "middle", "font-size": 14, fill: "#6b7280" });
          } else {
            const allTau = taMsdSeries.flatMap(s => s.tau_vals || []).filter(v => v > 0);
            const allMsd = taMsdSeries.flatMap(s => {
              const msdVals = s.ta_msd_vals || [];
              const seVals = s.ta_msd_standard_error_vals || [];
              return msdVals.flatMap((msd, idx) => {
                const se = Number(seVals[idx] || 0);
                const values = [msd];
                if (Number.isFinite(se) && se > 0) {
                  values.push(msd + se);
                  if (msd - se > 0) values.push(msd - se);
                }
                return values;
              });
            }).filter(v => v > 0);
            let xMin = Math.min(...allTau);
            let xMax = Math.max(...allTau);
            let yMin = Math.min(...allMsd);
            let yMax = Math.max(...allMsd);
            if (xMin === xMax) xMax = xMin + 1;
            if (yMin === yMax) yMax = yMin * 1.1;
            const xScale = value => topPanel.x + ((log10(value) - log10(xMin)) / (log10(xMax) - log10(xMin))) * topPanel.width;
            const yScale = value => topPanel.y + topPanel.height - ((log10(value) - log10(yMin)) / (log10(yMax) - log10(yMin))) * topPanel.height;
            drawAxes(svg, topPanel, logTicks(xMin, xMax), logTicks(yMin, yMax), xScale, yScale, "Lag tau (days)", "TA-MSD");

            taMsdSeries.forEach((s) => {
              const color = colors[s._seriesIndex % colors.length];
              const seVals = s.ta_msd_standard_error_vals || [];
              const points = (s.tau_vals || []).map((tau, idx) => [tau, s.ta_msd_vals[idx], Number(seVals[idx] || 0)]).filter(point => point[0] > 0 && point[1] > 0);
              points.forEach(([tau, msd, se]) => {
                if (Number.isFinite(se) && se > 0) {
                  const errorLow = Math.max(msd - se, yMin);
                  const errorHigh = msd + se;
                  const x = xScale(tau);
                  const yLow = yScale(errorLow);
                  const yHigh = yScale(errorHigh);
                  svg.appendChild(svgEl("line", { x1: x, y1: yHigh, x2: x, y2: yLow, stroke: color, "stroke-width": 1.2, opacity: 0.45 }));
                  svg.appendChild(svgEl("line", { x1: x - 4, y1: yHigh, x2: x + 4, y2: yHigh, stroke: color, "stroke-width": 1.2, opacity: 0.45 }));
                  svg.appendChild(svgEl("line", { x1: x - 4, y1: yLow, x2: x + 4, y2: yLow, stroke: color, "stroke-width": 1.2, opacity: 0.45 }));
                }
                svg.appendChild(svgEl("circle", { cx: xScale(tau), cy: yScale(msd), r: 3, fill: color, opacity: 0.85 }));
              });

              const fitTau = linspace(Math.max(xMin, s.lag_min || xMin), Math.min(xMax, s.lag_max || xMax), 80);
              const fitPoints = fitTau.map(tau => {
                const y = Math.pow(10, s.alpha * log10(tau) + s.beta);
                return [xScale(tau), yScale(y)];
              });
              svg.appendChild(svgEl("path", { d: pathFromPoints(fitPoints), fill: "none", stroke: color, "stroke-width": 2.2, opacity: 0.9 }));
            });
          }

          frequencySeries.forEach((s, i) => {
            const yOffset = topPanel.y + topPanel.height + panelGap + i * (freqPanelHeight + panelGap);
            const panel = { x: margin.left, y: yOffset, width: plotWidth, height: freqPanelHeight };
            const dates = s.dates || [];
            const freqs = s.mutant_freq || [];
            const dateMin = Math.min(...dates);
            const dateMax = Math.max(...dates);
            const fx = value => panel.x + ((value - dateMin) / Math.max(dateMax - dateMin, 1)) * panel.width;
            const fy = value => panel.y + panel.height - value * panel.height;
            drawAxes(svg, panel, linearTicks(dateMin, dateMax, 5), linearTicks(0, 1, 6), fx, fy, "Date", "Mutant frequency", formatDateTick, formatTick);
            addText(svg, `Mutant frequency - ${s.label}`, panel.x, panel.y - 14, { "font-size": 14, "font-weight": 700, fill: "#111827" });

            const wfMean = s.wf_fitted_mean || [];
            const wfPoints = dates.map((date, idx) => [date, wfMean[idx]]).filter(point => Number.isFinite(point[0]) && Number.isFinite(point[1]));
            if (wfPoints.length >= 2) {
              const wfPath = wfPoints.map(([date, mean]) => [fx(date), fy(Math.max(0, Math.min(1, mean)))]);
              svg.appendChild(svgEl("path", {
                d: pathFromPoints(wfPath),
                fill: "none",
                stroke: "#111827",
                "stroke-width": 2.4,
                "stroke-dasharray": "7 4",
                opacity: 0.9,
              }));
              addText(svg, "WF mean", panel.x + panel.width - 72, panel.y + 18, { "font-size": 12, "font-weight": 700, fill: "#111827" });
            }

            dates.forEach((date, idx) => {
              svg.appendChild(svgEl("circle", { cx: fx(date), cy: fy(freqs[idx]), r: 3, fill: colors[s._seriesIndex % colors.length], opacity: 0.85 }));
            });
          });

          plotContainer.innerHTML = "";
          plotContainer.appendChild(svg);
        }

        fetch(plotDataUrl)
          .then(response => {
            if (!response.ok) throw new Error("Plot data could not be loaded.");
            return response.json();
          })
          .then(data => {
            populatePlotControls(data);
            renderPlot(data);
          })
          .catch(error => {
            plotContainer.innerHTML = `<div class="plot-message">${error.message}</div>`;
          });
      </script>

    {% else %}
      <div class="empty">No site regression data found. Run generate_plots.py first.</div>
    {% endif %}
  </main>
</body>
</html>
"""


INTERVAL_BROWSER_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TA MSD Interval Browser</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Arial, Helvetica, sans-serif;
      color: #1f2937;
      background: #f3f4f6;
    }
    body {
      margin: 0;
      padding: 32px;
    }
    main {
      max-width: 1280px;
      margin: 0 auto;
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
      padding: 28px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 28px;
    }
    .meta {
      margin: 0 0 22px;
      color: #6b7280;
      font-size: 14px;
    }
    .nav {
      display: flex;
      gap: 14px;
      margin: 0 0 22px;
      font-size: 14px;
    }
    .nav a {
      color: #2563eb;
      font-weight: 700;
      text-decoration: none;
    }
    .nav a:hover {
      text-decoration: underline;
    }
    form {
      display: flex;
      flex-wrap: wrap;
      gap: 12px 16px;
      align-items: end;
      margin-bottom: 24px;
      padding: 14px;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      background: #f8fafc;
    }
    label {
      display: grid;
      gap: 6px;
      font-weight: 700;
      font-size: 13px;
      color: #374151;
    }
    select,
    button {
      min-width: 190px;
      padding: 8px 10px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      font-size: 15px;
      background: #fff;
    }
    button {
      min-width: 110px;
      color: #fff;
      background: #2563eb;
      border-color: #2563eb;
      font-weight: 700;
      cursor: pointer;
    }
    .pager {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin: 0 0 18px;
      padding: 12px 0;
      color: #4b5563;
      font-size: 14px;
    }
    .pager-links {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .pager a,
    .pager .disabled {
      display: inline-block;
      padding: 7px 10px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 700;
    }
    .pager a {
      color: #2563eb;
      background: #fff;
    }
    .pager .disabled {
      color: #9ca3af;
      background: #f3f4f6;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
      gap: 18px;
    }
    .card {
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      background: #fff;
      overflow: hidden;
    }
    .mini-plot {
      height: 220px;
      border-bottom: 1px solid #e5e7eb;
      background: #fff;
    }
    .mini-plot svg {
      display: block;
      width: 100%;
      height: 100%;
    }
    .card-body {
      padding: 12px 14px 14px;
      font-size: 13px;
      color: #374151;
    }
    .card-title {
      margin: 0 0 6px;
      font-size: 15px;
      font-weight: 700;
      color: #111827;
    }
    .card-body a {
      color: #2563eb;
      font-weight: 700;
      text-decoration: none;
    }
    .card-body a:hover {
      text-decoration: underline;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px 10px;
      margin: 8px 0;
      color: #4b5563;
    }
    .empty {
      padding: 24px;
      border: 1px dashed #cbd5e1;
      border-radius: 10px;
      color: #6b7280;
    }
  </style>
</head>
<body>
  <main>
    <h1>Interval Browser</h1>
    <p class="meta">Filter intervals across {{ countries|length }} country/region data sets.</p>
    <nav class="nav">
      <a href="{{ url_for('index') }}">Site viewer</a>
      <a href="{{ url_for('interval_browser', alpha=selected_alpha, wf_r2=selected_wf_r2, residual_alpha=selected_residual_alpha) }}">Browse intervals</a>
    </nav>

    <form method="get">
      <label>
        Alpha label
        <select name="alpha">
          {% for value, label in alpha_filters %}
            <option value="{{ value }}" {% if value == selected_alpha %}selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
      </label>
      <label>
        WF R²
        <select name="wf_r2">
          {% for value, label in wf_r2_filters %}
            <option value="{{ value }}" {% if value == selected_wf_r2 %}selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
      </label>
      <label>
        Residual alpha
        <select name="residual_alpha">
          {% for value, label in residual_alpha_filters %}
            <option value="{{ value }}" {% if value == selected_residual_alpha %}selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
      </label>
      <label>
        Per page
        <select name="page_size">
          {% for value in [12, 24, 48, 96] %}
            <option value="{{ value }}" {% if value == page_size %}selected{% endif %}>{{ value }}</option>
          {% endfor %}
        </select>
      </label>
      <input type="hidden" name="page" value="1">
      <button type="submit">Apply</button>
    </form>

    <div class="pager">
      <div>
        Showing {{ cards|length }} of {{ total_cards }} matched interval{{ "" if total_cards == 1 else "s" }}.
        Page {{ page }} of {{ total_pages }}.
      </div>
      <div class="pager-links">
        {% if page > 1 %}
          <a href="{{ url_for('interval_browser', alpha=selected_alpha, wf_r2=selected_wf_r2, residual_alpha=selected_residual_alpha, page=page-1, page_size=page_size) }}">Previous</a>
        {% else %}
          <span class="disabled">Previous</span>
        {% endif %}
        {% if page < total_pages %}
          <a href="{{ url_for('interval_browser', alpha=selected_alpha, wf_r2=selected_wf_r2, residual_alpha=selected_residual_alpha, page=page+1, page_size=page_size) }}">Next</a>
        {% else %}
          <span class="disabled">Next</span>
        {% endif %}
      </div>
    </div>

    {% if cards %}
      <div class="grid">
        {% for card in cards %}
          <article class="card">
            <div id="mini-plot-{{ loop.index0 }}" class="mini-plot"></div>
            <div class="card-body">
              <p class="card-title">{{ card.country }} | Site {{ card.site }}</p>
              <div>{{ card.label }} | {{ card.phase_label }}</div>
              <div class="stats">
                <div>Alpha: {{ card.alpha_label }}</div>
                <div>Residual: {{ card.residual_alpha_label }}</div>
                <div>WF R²: {{ format_number(card.wf_r_squared) }}</div>
                <div>WF s: {{ format_number(card.get("wf_selection_coefficient")) }}</div>
              </div>
              <a href="{{ url_for('index', country=card.country, site=card.site) }}" target="_blank" rel="noopener">Open full site page</a>
            </div>
          </article>
        {% endfor %}
      </div>
      <div class="pager">
        <div>Page {{ page }} of {{ total_pages }}</div>
        <div class="pager-links">
          {% if page > 1 %}
            <a href="{{ url_for('interval_browser', alpha=selected_alpha, wf_r2=selected_wf_r2, residual_alpha=selected_residual_alpha, page=page-1, page_size=page_size) }}">Previous</a>
          {% else %}
            <span class="disabled">Previous</span>
          {% endif %}
          {% if page < total_pages %}
            <a href="{{ url_for('interval_browser', alpha=selected_alpha, wf_r2=selected_wf_r2, residual_alpha=selected_residual_alpha, page=page+1, page_size=page_size) }}">Next</a>
          {% else %}
            <span class="disabled">Next</span>
          {% endif %}
        </div>
      </div>
    {% else %}
      <div class="empty">No intervals matched the selected conditions.</div>
    {% endif %}
  </main>

  <script>
    const cards = {{ cards|tojson }};

    function svgEl(name, attrs = {}) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", name);
      for (const [key, value] of Object.entries(attrs)) {
        el.setAttribute(key, value);
      }
      return el;
    }

    function pathFromPoints(points) {
      return points.map((point, i) => `${i === 0 ? "M" : "L"}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(" ");
    }

    function addText(svg, text, x, y, attrs = {}) {
      const el = svgEl("text", { x, y, ...attrs });
      el.textContent = text;
      svg.appendChild(el);
    }

    function drawMiniPlot(container, card) {
      const series = card.series || {};
      const dates = series.dates || [];
      const freqs = series.mutant_freq || [];
      if (dates.length === 0 || freqs.length === 0) {
        container.innerHTML = '<div style="padding:18px;color:#6b7280;">No frequency data.</div>';
        return;
      }

      const width = 360;
      const height = 220;
      const margin = { left: 44, right: 16, top: 18, bottom: 34 };
      const panel = {
        x: margin.left,
        y: margin.top,
        width: width - margin.left - margin.right,
        height: height - margin.top - margin.bottom,
      };
      const dateMin = Math.min(...dates);
      const dateMax = Math.max(...dates);
      const fx = value => panel.x + ((value - dateMin) / Math.max(dateMax - dateMin, 1)) * panel.width;
      const fy = value => panel.y + panel.height - Math.max(0, Math.min(1, value)) * panel.height;
      const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Mutant frequency plot" });

      svg.appendChild(svgEl("rect", { x: panel.x, y: panel.y, width: panel.width, height: panel.height, fill: "#fff", stroke: "#d1d5db" }));
      for (const tick of [0, 0.25, 0.5, 0.75, 1]) {
        const y = fy(tick);
        svg.appendChild(svgEl("line", { x1: panel.x, y1: y, x2: panel.x + panel.width, y2: y, stroke: "#eef2f7" }));
        addText(svg, tick.toFixed(2).replace(/0+$/, "").replace(/\.$/, ""), panel.x - 8, y + 4, { "text-anchor": "end", "font-size": 10, fill: "#6b7280" });
      }

      const points = dates.map((date, idx) => [fx(date), fy(freqs[idx])]);
      svg.appendChild(svgEl("path", { d: pathFromPoints(points), fill: "none", stroke: "#9ca3af", "stroke-width": 1.4, opacity: 0.8 }));
      points.forEach(([x, y]) => {
        svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 2.6, fill: "#2563eb", opacity: 0.85 }));
      });

      const wfMean = series.wf_fitted_mean || [];
      const wfPoints = dates.map((date, idx) => [date, wfMean[idx]]).filter(point => Number.isFinite(point[0]) && Number.isFinite(point[1]));
      if (wfPoints.length >= 2) {
        const path = wfPoints.map(([date, mean]) => [fx(date), fy(mean)]);
        svg.appendChild(svgEl("path", { d: pathFromPoints(path), fill: "none", stroke: "#111827", "stroke-width": 2.2, "stroke-dasharray": "7 4" }));
        addText(svg, "WF mean", panel.x + panel.width - 62, panel.y + 15, { "font-size": 11, "font-weight": 700, fill: "#111827" });
      }

      addText(svg, "Mutant frequency", panel.x, height - 10, { "font-size": 11, "font-weight": 700, fill: "#374151" });
      container.innerHTML = "";
      container.appendChild(svg);
    }

    cards.forEach((card, index) => {
      const container = document.getElementById(`mini-plot-${index}`);
      if (container) drawMiniPlot(container, card);
    });
  </script>
</body>
</html>
"""


ERROR_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>TA MSD Regression Viewer</title>
</head>
<body>
  <h1>TA MSD Regression Viewer</h1>
  <p>{{ error }}</p>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
