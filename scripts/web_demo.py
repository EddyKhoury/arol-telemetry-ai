"""Local browser UI for the integrated AROL demo. Run from the repo root."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import streamlit as st

# Streamlit runs this file as a script; make repository imports explicit.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.demo_agent import answer_one, resolve_manifest  # noqa: E402
from src.common import config as config_mod  # noqa: E402

DEFAULT_MANIFEST = (
    "data/event_pools/continuous-20260924-080513-930170/manifest.json"
)

st.set_page_config(page_title="AROL telemetry demo", layout="wide")
st.title("AROL telemetry analysis")
st.caption("Local, scoped analysis of observed capping-machine telemetry")

if Path.cwd().resolve() != ROOT:
    st.error(f"Start the app from the repository root: {ROOT}")
    st.stop()

# The manifest is selected by the operator, not by an untrusted web input.
requested_manifest = os.environ.get("AROL_MANIFEST", DEFAULT_MANIFEST)
try:
    manifest_path, manifest = resolve_manifest(requested_manifest, ROOT)
except ValueError as exc:
    st.error(str(exc))
    st.info("Set AROL_MANIFEST to a complete local pool manifest and restart.")
    st.stop()

machine = manifest["summary"]["machine_id"]
st.caption(f"Selected machine: {machine} | Planner: rules")

window = (
    f"for machine {machine} from 2026-02-01T00:00:00 "
    "until 2026-02-01T12:00:00"
)
examples = {
    "Write my own question": "",
    "Torque summary and distribution": (
        "Summarize torque and show its distribution with 10 bins "
        f"{window} for head 5 for successful closures"
    ),
    "Head 5 success rate": f"Success rate for head 5 {window}",
}

chosen = st.selectbox("Choose an example", list(examples))
question = st.text_area(
    "Question",
    value=examples[chosen],
    key=f"question_{chosen}",
    height=110,
    placeholder="Ask for a machine, time window, head, and analysis.",
)

if st.button("Analyze", type="primary"):
    st.session_state.pop("result", None)
    query = question.strip()
    if not query:
        st.error("Enter a question or select an example.")
    elif len(query) > 1000:
        st.error("Keep the question under 1,000 characters.")
    else:
        # Each browser session has a separate directory and numbered questions.
        if "output_dir" not in st.session_state:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            st.session_state["output_dir"] = (
                ROOT / "data" / "web_demo_runs"
                / f"session-{stamp}-{uuid4().hex[:8]}"
            )
        sequence = st.session_state.get("sequence", 0) + 1
        st.session_state["sequence"] = sequence

        cfg = config_mod.load()
        cfg.setdefault("data", {}).update(
            source="person_a_pool", person_a={"demo": str(manifest_path)}
        )
        cfg.setdefault("agent", {})["planner"] = "rules"

        try:
            with st.spinner("Analyzing the selected event window..."):
                response_json, status = answer_one(
                    query, cfg, st.session_state["output_dir"], sequence,
                    json_output=True, plots=True,
                )
            payload = json.loads(response_json)
            assert status == payload["status"]
            st.session_state["result"] = payload
        except Exception as exc:
            # Keep errors visible during this local presentation demo.
            st.error(f"Analysis could not be completed: {type(exc).__name__}: {exc}")

payload = st.session_state.get("result")
if payload is not None:
    status = payload["status"]
    if status == "ok":
        st.success("Analysis completed")
    elif status == "needs_clarification":
        st.info(payload.get("message") or "Please narrow or clarify the question.")
    else:
        st.warning(f"Analysis status: {status}")

    # deliver() appends relative PNG links to the saved Markdown file.
    # Streamlit displays their absolute local files below instead.
    saved_markdown = payload["markdown"]
    display_markdown = saved_markdown.split("\n## Figures\n", 1)[0]
    st.markdown(display_markdown)

    for index, name in enumerate(payload["artifacts"].get("figures", [])):
        image_path = Path(name)
        st.image(str(image_path), caption=image_path.stem.replace("_", " "))
        st.download_button(
            f"Download figure {index + 1}", image_path.read_bytes(),
            file_name=image_path.name, mime="image/png", key=f"figure-{index}",
        )

    trace_json = json.dumps(payload["trace"], indent=2, ensure_ascii=False)
    with st.expander("Execution trace and planned tools"):
        st.write("Planned calls:", payload["planned_calls"])
        st.json(payload["trace"])

    st.download_button(
        "Download Markdown report", saved_markdown,
        file_name="arol-report.md", mime="text/markdown", key="report",
    )
    st.download_button(
        "Download JSON trace", trace_json,
        file_name="arol-trace.json", mime="application/json", key="trace",
    )
    st.caption("Report and trace are also saved locally under data/web_demo_runs/.")
