#!/usr/bin/env python3
import os
import re
import sys
import json
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

GITHUB_API = os.environ.get("GITHUB_API", "https://api.github.com")
REPO = os.environ["GITHUB_REPOSITORY"]  # e.g. Neal-yes/AI_Support_System
TOKEN = os.environ["GITHUB_TOKEN"]
README_PATH = os.environ.get("README_PATH", "README.md")
WORKFLOW_FILE = os.environ.get("WORKFLOW_FILE", "progress.yml")

START_MARK = "<!-- PROGRESS_SECTION_START -->"
END_MARK = "<!-- PROGRESS_SECTION_END -->"


def gh_api(path: str):
    req = Request(f"{GITHUB_API}{path}")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        sys.stderr.write(f"HTTPError {e.code} for {path}: {e.read().decode('utf-8')[:200]}\n")
        raise
    except URLError as e:
        sys.stderr.write(f"URLError for {path}: {e}\n")
        raise


def find_latest_success_run():
    # List workflow runs by file name
    runs = gh_api(f"/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/runs?status=success&per_page=1")
    items = runs.get("workflow_runs", [])
    if not items:
        return None
    return items[0]


def list_artifacts(run_id: int):
    data = gh_api(f"/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
    return data.get("artifacts", [])


def build_readme_block(run):
    run_id = run["id"]
    html_url = run["html_url"]
    # Fetch artifacts and construct links to artifact detail pages
    arts = list_artifacts(run_id)
    # Map some common artifact names if present
    name_to_art = {a["name"]: a for a in arts}

    lines = []
    lines.append("### 进度报告（Progress Report）")
    lines.append("")
    lines.append(f"- 工作流页：https://github.com/{REPO}/actions/workflows/{WORKFLOW_FILE}")
    lines.append(f"- 最近一次运行（成功）：{html_url}")
    if arts:
        lines.append("- 工件（Artifacts）：")
        for a in arts:
            page_url = f"https://github.com/{REPO}/actions/runs/{run_id}/artifacts/{a['id']}"
            lines.append(f"  - {a['name']}：{page_url}")
    else:
        lines.append("- 工件（Artifacts）：无")
    return "\n".join(lines) + "\n"


def replace_block(content: str, new_block: str) -> str:
    pattern = re.compile(
        rf"{re.escape(START_MARK)}[\s\S]*?{re.escape(END_MARK)}",
        re.MULTILINE,
    )
    replacement = f"{START_MARK}\n{new_block}{END_MARK}"
    if pattern.search(content):
        return pattern.sub(replacement, content)
    # If markers not found, append at top after badges
    return replacement + "\n\n" + content


def main():
    latest = find_latest_success_run()
    if not latest:
        print("No successful Progress Report run found; skipping")
        return 0
    block = build_readme_block(latest)

    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = replace_block(content, block)

    if new_content == content:
        print("README up-to-date; no change")
        return 0

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("README updated with latest Progress Report links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
