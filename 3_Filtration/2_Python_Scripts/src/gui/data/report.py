from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import yaml
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.gridspec import GridSpec

from src.gui.frames.analysis_frame import parse_telemetry_csv

logger = logging.getLogger(__name__)


def generate_report(run_dir: Path) -> Optional[Path]:
    """Generate a PDF summary for a completed run. Returns the PDF path or None on failure."""
    run_dir = Path(run_dir)
    telemetry_csv = run_dir / "telemetry.csv"
    events_csv = run_dir / "events.csv"
    meta_yaml = run_dir / "meta.yaml"
    pdf_path = run_dir / "report.pdf"

    try:
        run = parse_telemetry_csv(telemetry_csv)
    except Exception as exc:
        logger.warning("Report: could not parse telemetry CSV: %s", exc)
        return None

    meta: dict = {}
    if meta_yaml.is_file():
        try:
            with open(meta_yaml, encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("Report: could not parse meta.yaml: %s", exc)

    annotations: list = []
    if events_csv.is_file():
        try:
            with open(events_csv, newline="", encoding="utf-8") as f:
                annotations = [
                    r for r in csv.DictReader(f) if r.get("type") == "ANNOTATION"
                ]
        except Exception:
            pass

    run_id = meta.get("run_id", run_dir.name)
    run_params = (meta.get("meta", {}) or {}).get("run_params", {}) or {}
    env = meta.get("env", {}) or {}

    try:
        with PdfPages(str(pdf_path)) as pdf:
            fig = plt.figure(figsize=(11, 17), constrained_layout=True)
            gs = GridSpec(5, 1, figure=fig, height_ratios=[0.4, 2.2, 2.0, 2.0, 1.8])

            # --- Title ---
            ax_t = fig.add_subplot(gs[0])
            ax_t.axis("off")
            ax_t.text(0.5, 0.85, "Pellikan OS — Run Report",
                      transform=ax_t.transAxes, ha="center", va="top",
                      fontsize=18, fontweight="bold", color="#0F172A")
            ax_t.text(0.5, 0.45, f"Run: {run_id}",
                      transform=ax_t.transAxes, ha="center", va="top",
                      fontsize=11, color="#334155")
            ax_t.text(
                0.5, 0.08,
                f"Duration: {run.duration_s:.1f} s  |  Points: {run.n_points:,}  |  "
                f"User: {env.get('user', '—')}  |  Host: {env.get('computer', '—')}",
                transform=ax_t.transAxes, ha="center", va="top",
                fontsize=9, color="#64748B",
            )

            t = run.time_s - run.time_s[0]

            def _add_annotation_markers(ax):
                ymin, ymax = ax.get_ylim()
                for ann in annotations:
                    try:
                        t_ann = float(ann.get("t_s", 0))
                        payload = json.loads(ann.get("payload_json", "{}") or "{}")
                        ax.axvline(t_ann, color="#EC4899", alpha=0.55, lw=1, ls="--")
                        ax.text(t_ann, ymax * 0.93, payload.get("text", "")[:20],
                                fontsize=5.5, color="#EC4899", rotation=90, va="top")
                    except Exception:
                        pass

            # --- Pressure ---
            ax_p = fig.add_subplot(gs[1])
            ax_p.plot(t, run.pressure_mbar, color="#8B5CF6", lw=1.5)
            ax_p.set_ylabel("Pressure [mbar]", fontsize=9, color="#4B5563")
            ax_p.set_title("Pressure", loc="left", fontsize=9, color="#374151")
            ax_p.grid(alpha=0.3)
            ax_p.tick_params(labelbottom=False, labelsize=8)
            _add_annotation_markers(ax_p)

            # --- Volume ---
            ax_v = fig.add_subplot(gs[2])
            ax_v.plot(t, run.volume_ml, color="#10B981", lw=1.5)
            ax_v.set_ylabel("Volume [mL]", fontsize=9, color="#4B5563")
            ax_v.set_title("Cumulative Volume (Loss)", loc="left", fontsize=9, color="#374151")
            ax_v.grid(alpha=0.3)
            ax_v.tick_params(labelbottom=False, labelsize=8)
            _add_annotation_markers(ax_v)

            # --- Flow (derived) ---
            ax_f = fig.add_subplot(gs[3])
            if len(t) > 2:
                dt = np.diff(t)
                dt[dt < 1e-6] = 1e-6
                flow = np.diff(run.volume_ml) / dt * 60.0
                ax_f.plot(t[1:], flow, color="#F59E0B", lw=1.2)
            ax_f.set_ylabel("Flow [mL/min]", fontsize=9, color="#4B5563")
            ax_f.set_xlabel("Elapsed Time [s]", fontsize=9, color="#4B5563")
            ax_f.set_title("Estimated Flow Rate", loc="left", fontsize=9, color="#374151")
            ax_f.grid(alpha=0.3)
            ax_f.tick_params(labelsize=8)

            # --- KPI table ---
            ax_tbl = fig.add_subplot(gs[4])
            ax_tbl.axis("off")
            kpi_rows = [
                ["Target Pressure", f"{run_params.get('phase_a_target_mbar', '—')} mbar"],
                ["Ramp Rate", f"{run_params.get('phase_a_rate_mbar_min', '—')} mbar/min"],
                ["B1 Target Vol.", f"{run_params.get('phase_b1_target_ml', '—')} mL"],
                ["Max Pressure", f"{float(np.max(run.pressure_mbar)):.1f} mbar"],
                ["Max Volume", f"{float(np.max(run.volume_ml)):.1f} mL"],
                ["Duration", f"{run.duration_s:.1f} s"],
                ["Annotations", str(len(annotations))],
            ]
            tbl = ax_tbl.table(
                cellText=kpi_rows,
                colLabels=["Metric", "Value"],
                loc="center",
                cellLoc="center",
                bbox=[0.05, 0.0, 0.9, 1.0],
            )
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(9)
            for (row, col), cell in tbl.get_celld().items():
                if row == 0:
                    cell.set_facecolor("#1E293B")
                    cell.set_text_props(color="white", fontweight="bold")
                elif row % 2 == 0:
                    cell.set_facecolor("#F1F5F9")
                    cell.set_text_props(color="#0F172A")
                else:
                    cell.set_facecolor("white")
                    cell.set_text_props(color="#0F172A")

            pdf.savefig(fig)
            plt.close(fig)

        logger.info("Run report generated: %s", pdf_path)
        return pdf_path

    except Exception as exc:
        logger.warning("Report generation failed: %s", exc)
        try:
            plt.close("all")
        except Exception:
            pass
        return None
