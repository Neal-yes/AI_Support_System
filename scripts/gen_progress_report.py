#!/usr/bin/env python3
"""
Generate weekly progress artifacts:
- artifacts/progress/progress_radar.png
- artifacts/progress/kanban.md
- artifacts/progress/summary.json

Inputs (via env or CLI optional flags):
- PROG_M1 (int/float percentage, default 65)
- PROG_M15 (int/float percentage, default 45)
- PROG_M2 (int/float percentage, default 15)

This script purposely has zero non-stdlib runtime deps except matplotlib, which
will be installed on-the-fly in the CI workflow step.
"""
from __future__ import annotations
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Dict, Tuple, Any

# Lazy import to allow running without matplotlib locally when not needed
try:
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
except Exception as e:  # pragma: no cover
    plt = None


@dataclass
class Progress:
    m1: float  # percentage
    m15: float
    m2: float

    def clamp(self) -> "Progress":
        def c(v: float) -> float:
            try:
                v = float(v)
            except Exception:
                v = 0.0
            return max(0.0, min(100.0, v))
        return Progress(c(self.m1), c(self.m15), c(self.m2))


def load_progress_from_env() -> Progress:
    def getf(k: str, default: float) -> float:
        v = os.getenv(k)
        if v is None or v == "":
            return default
        try:
            return float(v)
        except Exception:
            return default
    return Progress(
        m1=getf("PROG_M1", 65.0),
        m15=getf("PROG_M15", 45.0),
        m2=getf("PROG_M2", 15.0),
    ).clamp()


def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def make_radar_chart(p: Progress, out_png: str) -> None:
    if plt is None:
        raise RuntimeError("matplotlib is required to render radar chart")

    labels = ["M1", "M1.5", "M2"]
    values = [p.m1, p.m15, p.m2]

    # Radar requires the polygon to be closed
    angles = [n / float(len(labels)) * 2.0 * math.pi for n in range(len(labels))]
    angles += angles[:1]
    vals = values + values[:1]

    fig, ax = plt.subplots(subplot_kw=dict(polar=True), figsize=(6, 6), dpi=150)

    # Draw outline
    ax.set_theta_offset(math.pi / 2)
    ax.set_theta_direction(-1)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels)

    ax.set_rlabel_position(0)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20%", "40%", "60%", "80%", "100%"], color="gray", size=8)
    ax.set_ylim(0, 100)

    ax.plot(angles, vals, linewidth=2, linestyle="solid", color="#4C78A8")
    ax.fill(angles, vals, color="#4C78A8", alpha=0.25)

    ax.set_title("Weekly Progress Radar", va="bottom")

    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)


def write_kanban_md(p: Progress, out_md: str) -> None:
    # Optional sections
    rag_path = os.path.join('artifacts', 'metrics', 'rag_eval.json')
    rag: Dict[str, Any] = {}
    try:
        if os.path.isfile(rag_path):
            with open(rag_path, 'r', encoding='utf-8') as f:
                rag = json.load(f)
    except Exception:
        rag = {}

    backup_path = os.path.join('artifacts', 'metrics', 'backup_health.json')
    backup: Dict[str, Any] = {}
    try:
        if os.path.isfile(backup_path):
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup = json.load(f)
    except Exception:
        backup = {}

    hr = rag.get('summary', {}).get('hit_ratio') if isinstance(rag, dict) else None
    at1 = rag.get('summary', {}).get('avg_top1') if isinstance(rag, dict) else None
    tot = rag.get('summary', {}).get('total') if isinstance(rag, dict) else None

    collections_count = None
    if isinstance(backup, dict):
        # qdrant /collections returns { result: { collections: [...] }, time, status }
        try:
            collections = backup.get('result', {}).get('collections', [])
            if isinstance(collections, list):
                collections_count = len(collections)
        except Exception:
            collections_count = None

    # Precompute optional sections to avoid backslashes in f-string expressions
    rag_section = ""
    if hr is not None or at1 is not None or tot is not None:
        rag_lines = [
            "",
            "## RAG 基线摘要",
            f"- total: {tot}",
            (f"- hit_ratio: {hr:.3f}" if isinstance(hr, (int, float)) else f"- hit_ratio: {hr}"),
            (f"- avg_top1: {at1:.3f}" if isinstance(at1, (int, float)) else f"- avg_top1: {at1}"),
            "",
        ]
        rag_section = "\n".join(rag_lines)

    backup_section = ""
    if collections_count is not None:
        backup_lines = [
            "",
            "## 备份健康快照",
            f"- collections: {collections_count}",
            "",
        ]
        backup_section = "\n".join(backup_lines)

    content = f"""# 进度看板（自动生成）

- 生成时间（UTC）：{os.getenv('GITHUB_RUN_ATTEMPT') or ''}
- 工作流：{os.getenv('GITHUB_WORKFLOW') or ''}
- 运行：{os.getenv('GITHUB_RUN_ID') or ''}

## 完成度概览
- M1: {p.m1:.0f}%
- M1.5: {p.m15:.0f}%
- M2: {p.m2:.0f}%

## 建议下周优先事项
- 前端版本号一致性与 E2E 快照
- 发布前评测（CD）干跑与报告工件
- 恢复演练与记录模板

## 关联工件（若存在）
- RAG 指标：artifacts/metrics/rag_eval.json / rag_eval.csv
- Smoke 摘要：artifacts/metrics/smoke_summary.md
- Playwright：playwright-report / playwright-junit-xml
""" + rag_section + backup_section
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(content)


def write_summary_json(p: Progress, out_json: str) -> None:
    payload: Dict[str, Any] = {"M1": p.m1, "M1_5": p.m15, "M2": p.m2}
    # Enrich with optional metrics snapshots
    rag_path = os.path.join('artifacts', 'metrics', 'rag_eval.json')
    if os.path.isfile(rag_path):
        try:
            with open(rag_path, 'r', encoding='utf-8') as f:
                rag = json.load(f)
            if isinstance(rag, dict) and 'summary' in rag:
                s = rag.get('summary') or {}
                payload['RAG'] = {
                    'total': s.get('total'),
                    'hit_ratio': s.get('hit_ratio'),
                    'avg_top1': s.get('avg_top1'),
                }
        except Exception:
            pass
    backup_path = os.path.join('artifacts', 'metrics', 'backup_health.json')
    if os.path.isfile(backup_path):
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup = json.load(f)
            if isinstance(backup, dict):
                cols = backup.get('result', {}).get('collections', []) if backup.get('result') else None
                payload['Backup'] = {
                    'collections_count': len(cols) if isinstance(cols, list) else None
                }
        except Exception:
            pass
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> int:
    progress = load_progress_from_env()
    out_dir = os.path.join("artifacts", "progress")
    ensure_dir(out_dir)

    out_png = os.path.join(out_dir, "progress_radar.png")
    out_md = os.path.join(out_dir, "kanban.md")
    out_json = os.path.join(out_dir, "summary.json")

    radar_ok = True
    try:
        make_radar_chart(progress, out_png)
    except Exception as e:
        radar_ok = False
        # Fallback: create a placeholder note to explain missing chart
        placeholder = os.path.join(out_dir, "NO_RADAR.txt")
        with open(placeholder, "w", encoding="utf-8") as f:
            f.write(
                "Radar chart was not generated. Reason: " + str(e) + "\n"
                "Tip: install a compatible matplotlib (e.g. in a venv) or run in CI where it is pre-installed.\n"
            )
        print(f"[progress][warn] Skip radar chart: {e}")

    write_kanban_md(progress, out_md)
    write_summary_json(progress, out_json)

    outputs = [out_md, out_json]
    if radar_ok:
        outputs.insert(0, out_png)
    else:
        outputs.insert(0, os.path.join(out_dir, "NO_RADAR.txt"))

    print("[progress] Wrote:\n" + "\n".join(outputs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
