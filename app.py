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
            <th>Consensus base</th>
            <th>Mutant base</th>
            <th>Start</th>
            <th>End</th>
            <th>Alpha coefficient</th>
            <th>Alpha 95% CI</th>
            <th>R²</th>
            <th>Diffusion type</th>
            <th>Days</th>
          </tr>
        </thead>
        <tbody>
          {% for interval in site_data.get("intervals", []) %}
            <tr class="interval-row" data-interval-index="{{ loop.index0 }}">
              <td>{{ interval.label }}</td>
              <td>{{ interval.get("most_common_aa") or "-" }}</td>
              <td>{{ interval.get("second_most_common_aa") or "-" }}</td>
              <td>{{ interval.start_date }} ({{ interval.start }})</td>
              <td>{{ interval.end_date }} ({{ interval.end }})</td>
              <td>{{ "%.6g"|format(interval.slope) }}</td>
              <td>{{ format_ci(interval.get("alpha_ci_low"), interval.get("alpha_ci_high")) }}</td>
              <td>{{ "%.6g"|format(interval.get("r_squared", 0)) }}</td>
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
            const status = s.show_in_ta_msd_plot === false ? "inconclusive" : (s.diffusion_label || "unlabeled");
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
            const allMsd = taMsdSeries.flatMap(s => s.ta_msd_vals || []).filter(v => v > 0);
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
              const points = (s.tau_vals || []).map((tau, idx) => [tau, s.ta_msd_vals[idx]]).filter(point => point[0] > 0 && point[1] > 0);
              points.forEach(([tau, msd]) => {
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
