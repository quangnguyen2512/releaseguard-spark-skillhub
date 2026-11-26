# -*- coding: utf-8 -*-
"""Self-contained 4-Panel Interactive HTML Visual Walkthrough Generator.

Designed specifically for HER Hack-Astron #8 (Spark-X2.6-4B x SkillHub) reviewers
and consecutive screenshot / 2-5 minute video capture:
- Panel 1: Sample Input (`RN-1..N` + Unified `git diff` + Pre-Committed Gold Criteria)
- Panel 2: SkillHub `global/changeradar` Deterministic AST Call-Graph & Test Compression
- Panel 3: Local `Spark-X2.6-4B` Prompt, `<think>` Trace & Verbatim Raw JSON Output
- Panel 4: 7-Gate Citation Verifier & Explicit Human Review (`Approved: 0 of N` -> Export JSON)
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def generate_html_walkthrough(summary_bundle: dict[str, Any], output_path: Path) -> Path:
    """Render a zero-dependency interactive HTML walkthrough report."""
    is_dry_run = bool(summary_bundle.get("is_dry_run", True))
    skill = summary_bundle.get("skill_provenance", {})
    env = summary_bundle.get("environment", {})
    runs = summary_bundle.get("samples", [])

    mode_badge = (
        "DRY-RUN PIPELINE PREVIEW — NO SPARK-X2.6-4B WEIGHTS EXECUTED (NOT FOR FINAL SUBMISSION)"
        if is_dry_run
        else f"VERIFIED LOCAL SPARK-X2.6-4B EXECUTION ({html.escape(str(summary_bundle.get('model_id', '')))} @ {html.escape(str(summary_bundle.get('model_revision', ''))[:12])})"
    )
    banner_bg = "#7c2d12" if is_dry_run else "#065f46"
    banner_border = "#f97316" if is_dry_run else "#10b981"

    embedded_json = json.dumps(summary_bundle, ensure_ascii=False).replace("</", "<\\/")

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>ReleaseGuard — Spark-X2.6-4B × SkillHub ChangeRadar Walkthrough</title>
<style>
  :root {{
    --bg: #0b1120;
    --panel: #111827;
    --panel-alt: #1e293b;
    --border: #334155;
    --text: #f1f5f9;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --ok: #10b981;
    --warn: #f59e0b;
    --err: #ef4444;
    --code-bg: #020617;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  .mode-banner {{
    background: {banner_bg};
    border-bottom: 2px solid {banner_border};
    padding: 10px 24px;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.03em;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .container {{ max-width: 1360px; margin: 0 auto; padding: 20px 24px 48px; }}
  .hero {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 18px;
  }}
  .hero h1 {{ margin: 0 0 6px; font-size: 24px; color: #fff; }}
  .hero p {{ margin: 0; color: var(--muted); font-size: 14px; max-width: 820px; }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    margin-bottom: 18px;
  }}
  .kpi {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
  }}
  .kpi .label {{ font-size: 11px; text-transform: uppercase; color: var(--muted); letter-spacing: 0.05em; }}
  .kpi .val {{ font-size: 20px; font-weight: 700; margin-top: 4px; color: var(--accent); }}
  .kpi .sub {{ font-size: 12px; color: var(--muted); margin-top: 2px; word-break: break-all; }}
  .toolbar {{
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 16px;
    background: var(--panel);
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid var(--border);
  }}
  select, button, input[type="text"] {{
    background: var(--panel-alt);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
  }}
  button {{ cursor: pointer; font-weight: 600; transition: background 0.15s; }}
  button:hover {{ background: #334155; }}
  button.active-tab {{ background: #0284c7; border-color: #38bdf8; color: #fff; }}
  button.primary {{ background: #059669; border-color: #10b981; color: #fff; }}
  .panel {{
    display: none;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px 20px;
  }}
  .panel.visible {{ display: block; }}
  .panel h2 {{ margin-top: 0; font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 960px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
  pre {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    overflow-x: auto;
    font-size: 12.5px;
    line-height: 1.45;
    margin: 8px 0 0;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .rn-line {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 8px;
    font-size: 13px;
  }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
  }}
  .badge-ok {{ background: rgba(16,185,129,0.18); color: #34d399; border: 1px solid #059669; }}
  .badge-err {{ background: rgba(239,68,68,0.18); color: #f87171; border: 1px solid #dc2626; }}
  .badge-warn {{ background: rgba(245,158,11,0.18); color: #fbbf24; border: 1px solid #d97706; }}
  .badge-info {{ background: rgba(56,189,248,0.18); color: #38bdf8; border: 1px solid #0284c7; }}
  .trace-chain {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin: 14px 0;
  }}
  @media (max-width: 960px) {{ .trace-chain {{ grid-template-columns: 1fr; }} }}
  .trace-box {{
    background: var(--panel-alt);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
  }}
  .trace-box h4 {{ margin: 0 0 8px; font-size: 12px; color: var(--accent); text-transform: uppercase; }}
  .item-card {{
    background: var(--panel-alt);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 12px;
  }}
  .gate-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    margin-bottom: 6px;
    font-size: 13px;
  }}
  .review-controls {{
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px dashed var(--border);
  }}
</style>
</head>
<body>
<div class="mode-banner">
  <span>⚡ {mode_badge}</span>
  <span>HER Hack-Astron #8 · Developer Tools Track · SkillHub <code>{html.escape(str(skill.get("namespace", "global")))}/{html.escape(str(skill.get("slug", "changeradar")))}@{html.escape(str(skill.get("version", "")))}</code></span>
</div>

<div class="container">
  <div class="hero">
    <div>
      <h1>🛡️ ReleaseGuard — Verifiable Upgrade Checklist &amp; Breaking-Change Tracer</h1>
      <p>Turns public OSS release notes + unified <code>git diff</code> into a source-quoted developer upgrade checklist, tracing code changes through SkillHub <code>global/changeradar</code>'s deterministic AST call graph to affected features and regression tests, audited by 7 zero-hallucination gates.</p>
    </div>
    <div>
      <span class="badge {'badge-warn' if is_dry_run else 'badge-ok'}" style="font-size:13px;padding:6px 12px;">
        {'PREVIEW MODE (DRY-RUN)' if is_dry_run else 'REAL ON-DEVICE SPARK-X2.6-4B'}
      </span>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="label">SkillHub Skill &amp; SHA-256</div>
      <div class="val">{html.escape(str(skill.get("slug", "changeradar")))}</div>
      <div class="sub">v{html.escape(str(skill.get("version", "")))} · {html.escape(str(skill.get("fingerprint", ""))[:26])}…</div>
    </div>
    <div class="kpi">
      <div class="label">Samples Passing All 7 Gates</div>
      <div class="val">{summary_bundle.get("passed_samples", 0)} / {len(runs)}</div>
      <div class="sub">Verified items: {summary_bundle.get("verified_items_total", 0)} / {summary_bundle.get("items_total", 0)}</div>
    </div>
    <div class="kpi">
      <div class="label">AST Seed &amp; Caller Trace Recall</div>
      <div class="val">{round(float(summary_bundle.get("mean_caller_recall", 0.0)) * 100, 1)}%</div>
      <div class="sub">Test compression ratio: {round(float(summary_bundle.get("mean_test_compression", 0.0)) * 100, 1)}% selected</div>
    </div>
    <div class="kpi">
      <div class="label">Hardware &amp; Mean Latency</div>
      <div class="val">{summary_bundle.get("mean_latency_ms", 0.0)} ms</div>
      <div class="sub">{html.escape(str(env.get("cpu_model", "Local Host")))} · RAM {env.get("ram_total_gib", "?")} GiB</div>
    </div>
  </div>

  <div class="toolbar">
    <label for="sampleSelect"><strong>Release Sample:</strong></label>
    <select id="sampleSelect" onchange="selectSample(this.value)"></select>
    <button id="tabBtn1" class="active-tab" onclick="showTab(1)">1. Input &amp; Gold Criteria</button>
    <button id="tabBtn2" onclick="showTab(2)">2. SkillHub ChangeRadar AST Trace</button>
    <button id="tabBtn3" onclick="showTab(3)">3. Raw Spark-X2.6-4B Output</button>
    <button id="tabBtn4" onclick="showTab(4)">4. 7-Gate Audit &amp; Human Review</button>
    <span style="margin-left:auto;font-weight:700;color:var(--accent);" id="approvalCounter">Approved: 0 of 0</span>
  </div>

  <div id="panel1" class="panel visible"></div>
  <div id="panel2" class="panel"></div>
  <div id="panel3" class="panel"></div>
  <div id="panel4" class="panel"></div>
</div>

<script>
const DATA = {embedded_json};
let currentIdx = 0;
let activeTab = 1;
const reviewState = {{}}; // key: sampleId::itemId -> {{status: 'pending'|'accepted'|'corrected'|'rejected', note: ''}}

function esc(s) {{
  if (s === null || s === undefined) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}}

function init() {{
  const sel = document.getElementById('sampleSelect');
  DATA.samples.forEach((s, idx) => {{
    const opt = document.createElement('option');
    opt.value = idx;
    opt.textContent = `${{s.sample_id}} — ${{s.project}} (${{s.from_version}} → ${{s.to_version}})`;
    sel.appendChild(opt);
    (s.checklist_items || []).forEach(it => {{
      reviewState[`${{s.sample_id}}::${{it.id}}`] = {{ status: 'pending', note: '' }};
    }});
  }});
  const params = new URLSearchParams(window.location.search);
  if (params.has('sample')) {{
    const sIdx = Number(params.get('sample'));
    if (!Number.isNaN(sIdx) && sIdx >= 0 && sIdx < DATA.samples.length) {{
      currentIdx = sIdx;
      sel.value = String(sIdx);
    }}
  }}
  if (params.get('demo_decisions') === '1' && DATA.samples[currentIdx]) {{
    const s = DATA.samples[currentIdx];
    const items = s.checklist_items || [];
    if (items[0]) reviewState[`${{s.sample_id}}::${{items[0].id}}`] = {{ status: 'accepted', note: '' }};
    if (items[1]) reviewState[`${{s.sample_id}}::${{items[1].id}}`] = {{ status: 'accepted', note: '' }};
    if (items[2]) reviewState[`${{s.sample_id}}::${{items[2].id}}`] = {{ status: 'rejected', note: 'Unchanged default limits — omit from migration checklist' }};
  }}
  renderAll();
  if (params.has('tab')) {{
    const t = Number(params.get('tab'));
    if (t >= 1 && t <= 4) showTab(t);
  }}
}}

function selectSample(idx) {{
  currentIdx = Number(idx);
  renderAll();
}}

function showTab(n) {{
  activeTab = n;
  for (let i = 1; i <= 4; i++) {{
    document.getElementById('panel' + i).classList.toggle('visible', i === n);
    document.getElementById('tabBtn' + i).classList.toggle('active-tab', i === n);
  }}
}}

function setDecision(sampleId, itemId, decision) {{
  const key = `${{sampleId}}::${{itemId}}`;
  const noteInput = document.getElementById(`note_${{itemId}}`);
  const noteVal = noteInput ? noteInput.value.trim() : '';
  if (decision === 'corrected' && !noteVal) {{
    alert('Correction requires non-empty replacement/clarification text before approval.');
    return;
  }}
  reviewState[key] = {{ status: decision, note: noteVal }};
  renderPanel4();
  updateCounter();
}}

function updateCounter() {{
  const s = DATA.samples[currentIdx];
  if (!s) return;
  const items = s.checklist_items || [];
  let approved = 0;
  items.forEach(it => {{
    const st = (reviewState[`${{s.sample_id}}::${{it.id}}`] || {{}}).status;
    if (st === 'accepted' || st === 'corrected') approved += 1;
  }});
  document.getElementById('approvalCounter').textContent = `Approved: ${{approved}} of ${{items.length}}`;
}}

function downloadJson(filename, obj) {{
  const blob = new Blob([JSON.stringify(obj, null, 2)], {{ type: 'application/json' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}}

function exportApproved() {{
  const s = DATA.samples[currentIdx];
  const approvedItems = (s.checklist_items || []).filter(it => {{
    const st = reviewState[`${{s.sample_id}}::${{it.id}}`]?.status;
    return st === 'accepted' || st === 'corrected';
  }}).map(it => {{
    const st = reviewState[`${{s.sample_id}}::${{it.id}}`];
    return {{ ...it, review_status: st.status, human_correction: st.note || null }};
  }});
  downloadJson(`${{s.sample_id}}_approved_checklist.json`, {{
    sample_id: s.sample_id,
    project: s.project,
    is_dry_run: DATA.is_dry_run,
    approved_count: approvedItems.length,
    total_candidates: (s.checklist_items || []).length,
    approved_items: approvedItems
  }});
}}

function exportAuditLog() {{
  const s = DATA.samples[currentIdx];
  const logItems = (s.checklist_items || []).map(it => {{
    const st = reviewState[`${{s.sample_id}}::${{it.id}}`] || {{ status: 'pending', note: '' }};
    return {{
      item_id: it.id,
      original_item: it,
      human_decision: st.status,
      human_correction: st.note || null,
      approved: st.status === 'accepted' || st.status === 'corrected'
    }};
  }});
  downloadJson(`${{s.sample_id}}_full_review_log.json`, {{
    sample_id: s.sample_id,
    verification: s.verification,
    review_log: logItems
  }});
}}

function renderAll() {{
  const s = DATA.samples[currentIdx];
  if (!s) return;

  // Panel 1
  const rnHtml = (s.release_lines || []).map(ln =>
    `<div class="rn-line"><strong>[${{esc(ln.line_id)}}]</strong> (L${{ln.line_num}}) ${{esc(ln.text)}}</div>`
  ).join('');
  const critHtml = ((s.ground_truth || {{}}).acceptance_criteria || []).map(c => `<li>${{esc(c)}}</li>`).join('');
  document.getElementById('panel1').innerHTML = `
    <h2>Step 1 — Verbatim Public Release Notes, Unified Git Diff &amp; Pre-Committed Acceptance Criteria</h2>
    <p style="color:var(--muted);font-size:13px;">Source: <a href="${{esc(s.release_url)}}" style="color:var(--accent);" target="_blank">${{esc(s.release_url)}}</a> · License: <code>${{esc(s.license)}}</code> · Upgrade: <code>${{esc(s.from_version)}} → ${{esc(s.to_version)}}</code></p>
    <div class="two-col">
      <div>
        <h3>Numbered Public Release Notes</h3>
        ${{rnHtml}}
        <h3>Pre-Committed Acceptance Criteria (Locked Before Inference)</h3>
        <ul style="font-size:13px;color:#cbd5e1;">${{critHtml}}</ul>
      </div>
      <div>
        <h3>Unified Git Diff (<code>patch.diff</code>)</h3>
        <pre>${{esc(s.patch_diff_raw)}}</pre>
      </div>
    </div>
  `;

  // Panel 2
  const cr = s.changeradar || {{}};
  const seedsHtml = (cr.seed_nodes || []).map(x => `<div><code>${{esc(x)}}</code></div>`).join('');
  const callersHtml = (cr.affected_callers || []).map(x => `<div><code>${{esc(x)}}</code></div>`).join('');
  const selTestsHtml = (cr.selected_tests || []).map(t =>
    `<div><span class="badge badge-ok">${{esc(t.risk_level)}}</span> <code>${{esc(t.test_name)}}</code> (score=${{t.coupling_score}})</div>`
  ).join('');
  const exclHtml = ((s.ground_truth || {{}}).excluded_unrelated_tests || []).map(t =>
    `<div><span class="badge badge-info">skipped</span> <code>${{esc(t)}}</code></div>`
  ).join('');

  document.getElementById('panel2').innerHTML = `
    <h2>Step 2 — SkillHub <code>global/changeradar</code> Deterministic AST Call-Graph &amp; Test Selection</h2>
    <p style="color:var(--muted);font-size:13px;">Executed 6-script stdlib pipeline (<code>cache.py → callgraph.py → diffparse.py → propagate.py → testselect.py</code>). LLM never computes graph edges or metrics (<code>SKILL.md</code> Red Lines #1 &amp; #2).</p>
    <div class="trace-chain">
      <div class="trace-box"><h4>1. Diff Changed Files</h4>${{(cr.changed_files || []).map(f => `<div><code>${{esc(f)}}</code></div>`).join('')}}</div>
      <div class="trace-box"><h4>2. AST Seed Functions (distance=0)</h4>${{seedsHtml}}</div>
      <div class="trace-box"><h4>3. Affected Feature Callers (BFS)</h4>${{callersHtml}}</div>
      <div class="trace-box"><h4>4. Selected Regression Tests (${{cr.selected_tests?.length || 0}}/${{cr.total_tests || 0}})</h4>${{selTestsHtml}}<hr style="border-color:var(--border);margin:8px 0;"/>${{exclHtml}}</div>
    </div>
    <h3>Machine JSON Envelope Passed to Local Spark-X2.6-4B</h3>
    <pre>${{esc(JSON.stringify({{ propagate: cr.propagate?.data, testselect: cr.testselect?.data }}, null, 2))}}</pre>
  `;

  // Panel 3
  const inf = s.inference || {{}};
  const prompts = s.prompt_messages || [];
  document.getElementById('panel3').innerHTML = `
    <h2>Step 3 — Local <code>Spark-X2.6-4B</code> Execution Evidence (Prompt → Thinking → Raw JSON)</h2>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;font-size:13px;">
      <span class="badge ${{inf.is_dry_run ? 'badge-warn' : 'badge-ok'}}">Backend: ${{esc(inf.backend)}}</span>
      <span class="badge badge-info">Model: ${{esc(inf.model_id)}} (${{esc(inf.quantization_or_dtype)}})</span>
      <span class="badge badge-info">Revision: ${{esc((inf.model_revision || '').slice(0, 12))}}</span>
      <span class="badge badge-info">Thinking: ${{esc(inf.thinking_mode)}}</span>
      <span class="badge badge-info">Latency: ${{esc(inf.latency_ms)}} ms</span>
    </div>
    <div class="two-col">
      <div>
        <h3>Prompt Sent to Local Spark-X2.6-4B</h3>
        <pre>${{esc(prompts.map(m => `[${{m.role.toUpperCase()}}]\\n${{m.content}}`).join('\\n\\n---\\n\\n'))}}</pre>
      </div>
      <div>
        ${{s.thinking_trace ? `<h3>Extracted <code>&lt;think&gt;</code> Reasoning Trace</h3><pre>${{esc(s.thinking_trace)}}</pre>` : ''}}
        <h3>Verbatim Raw Model Output</h3>
        <pre>${{esc(inf.raw_text)}}</pre>
      </div>
    </div>
  `;

  renderPanel4();
  updateCounter();
}}

function renderPanel4() {{
  const s = DATA.samples[currentIdx];
  const ver = s.verification || {{}};
  const gatesHtml = (ver.gates || []).map(g => `
    <div class="gate-row">
      <div><strong>${{esc(g.gate_id)}} — ${{esc(g.name)}}</strong><div style="color:var(--muted);font-size:12px;">${{esc(g.summary)}} ${{g.violations?.length ? '· Violations: ' + esc(g.violations.join('; ')) : ''}}</div></div>
      <span class="badge ${{g.passed ? 'badge-ok' : 'badge-err'}}">${{g.passed ? 'PASS' : 'FAIL'}}</span>
    </div>
  `).join('');

  const itemsHtml = (s.checklist_items || []).map(it => {{
    const key = `${{s.sample_id}}::${{it.id}}`;
    const st = reviewState[key] || {{ status: 'pending', note: '' }};
    const tc = it.traced_change || {{}};
    const stBadge = st.status === 'accepted' ? 'badge-ok' : st.status === 'corrected' ? 'badge-info' : st.status === 'rejected' ? 'badge-err' : 'badge-warn';
    return `
      <div class="item-card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <div>
            <strong>${{esc(it.id)}}</strong> · <span class="badge ${{it.breaking ? 'badge-err' : 'badge-info'}}">${{it.breaking ? 'BREAKING' : esc(it.severity.toUpperCase())}}</span>
            · Source: <code>[${{esc(it.release_note_line_id)}}]</code>
          </div>
          <span class="badge ${{stBadge}}">Human Review: ${{esc(st.status.toUpperCase())}}</span>
        </div>
        <div style="font-weight:700;margin-top:6px;">${{esc(it.title)}}</div>
        <div style="font-size:13px;color:#cbd5e1;margin-top:4px;"><strong>Action:</strong> ${{esc(it.action)}}</div>
        <div style="font-size:12.5px;color:var(--muted);margin-top:6px;"><strong>Verbatim Quote:</strong> "${{esc(it.verbatim_quote)}}"</div>
        ${{it.uncertainty_note ? `<div style="font-size:12.5px;color:#fbbf24;margin-top:4px;"><strong>Uncertainty Preserved:</strong> ${{esc(it.uncertainty_note)}}</div>` : ''}}
        ${{tc.changed_symbol ? `
          <div style="font-size:12.5px;margin-top:6px;background:var(--code-bg);padding:8px;border-radius:6px;border:1px solid var(--border);">
            <strong>AST Feature Trace:</strong> <code>${{esc(tc.changed_file)}}</code> → Seed <code>${{esc(tc.changed_symbol)}}</code>
            → Affected Callers: <code>${{esc((tc.affected_features || []).join(', ') || 'none')}}</code>
            → Run Tests: <code>${{esc((tc.recommended_tests || []).join(', ') || 'none')}}</code>
          </div>` : ''}}
        <div class="review-controls">
          <button onclick="setDecision('${{esc(s.sample_id)}}', '${{esc(it.id)}}', 'accepted')">✅ Accept</button>
          <button onclick="setDecision('${{esc(s.sample_id)}}', '${{esc(it.id)}}', 'rejected')">❌ Reject</button>
          <input type="text" id="note_${{esc(it.id)}}" placeholder="Enter non-empty correction text..." value="${{esc(st.note)}}" style="flex:1;min-width:220px;" />
          <button onclick="setDecision('${{esc(s.sample_id)}}', '${{esc(it.id)}}', 'corrected')">✏️ Approve with Correction</button>
        </div>
      </div>
    `;
  }}).join('');

  document.getElementById('panel4').innerHTML = `
    <h2>Step 4 — 7-Gate Deterministic Citation Verifier &amp; Explicit Human Review Sign-Off</h2>
    <p style="color:var(--muted);font-size:13px;">Every item starts as <code>PENDING</code> (<code>Approved: 0 of N</code>). Nothing generated by the LLM is auto-approved without human sign-off.</p>
    <div style="margin-bottom:16px;">${{gatesHtml}}</div>
    <div style="display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap;">
      <button class="primary" onclick="exportApproved()">⬇ Export Approved Checklist JSON</button>
      <button onclick="exportAuditLog()">⬇ Export Full Review Audit Log JSON</button>
    </div>
    <h3>Generated Upgrade Checklist Items</h3>
    ${{itemsHtml}}
  `;
}}

init();
</script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")
    return output_path
