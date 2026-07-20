"""Minimal server-rendered incident UI (no frontend build)."""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import quote


def _esc(value: Any) -> str:
    return html.escape(str(value) if value is not None else "")


def _status_badge(status: str) -> str:
    return f'<span class="badge status-{ _esc(status) }">{ _esc(status) }</span>'


def _severity_badge(severity: str | None) -> str:
    sev = severity or "unknown"
    return f'<span class="badge severity-{ _esc(sev) }">{ _esc(sev) }</span>'


PAGE_SIZE = 25


def render_incident_rows(incidents: list[dict[str, Any]]) -> str:
    if not incidents:
        return ""
    rows = []
    for incident in incidents:
        iid = incident["id"]
        rows.append(
            f"""
            <div class="incident-row">
              <input class="row-check" type="checkbox" name="incident_id" value="{_esc(iid)}">
              <div>
                <a class="row-title" href="/incidents/{_esc(iid)}">{_esc(incident.get('title') or iid)}</a>
                <div class="muted">{_esc(iid)}</div>
              </div>
              <div>{_status_badge(str(incident.get('status') or 'open'))}</div>
              <div>{_severity_badge(incident.get('severity'))}</div>
              <div class="muted">{_esc(incident.get('updated_at') or '')}</div>
              <div><a href="/incidents/{_esc(iid)}">view →</a></div>
            </div>
            """
        )
    return "\n".join(rows)


def render_alert_rows(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return ""
    rows = []
    for alert in alerts:
        fp = str(alert.get("fingerprint") or "")
        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        title = annotations.get("summary") or labels.get("alertname") or fp
        rows.append(
            f"""
            <div class="incident-row">
              <input class="row-check" type="checkbox" name="fingerprint" value="{_esc(fp)}">
              <div>
                <strong class="row-title">{_esc(title)}</strong>
                <div class="muted">{_esc(labels.get('alertname', ''))} · {_esc(labels.get('namespace', ''))}</div>
              </div>
              <div>{_status_badge(str(alert.get('status') or 'firing'))}</div>
              <div>{_severity_badge(labels.get('severity'))}</div>
              <div class="muted">{_esc(alert.get('_updated_at') or '')}</div>
              <div>
                <button formaction="/alerts/{_esc(fp)}/raise" formmethod="post" type="submit">Raise</button>
              </div>
            </div>
            """
        )
    return "\n".join(rows)


def _lazy_list_script(*, kind: str, api_path: str, status_filter: str, checkbox_name: str, empty_message: str) -> str:
    placeholder = (
        'status:open severity>=warning title~"flux"'
        if kind == "incidents"
        else 'status:firing alertname:Homelab* namespace:flux-system'
    )
    return f"""
    <script>
    (function() {{
      const pageSize = {PAGE_SIZE};
      const apiPath = {json.dumps(api_path)};
      const checkboxName = {json.dumps(checkbox_name)};
      const emptyMessage = {json.dumps(empty_message)};
      const pollMs = 8000;
      let offset = 0;
      let hasMore = true;
      let loading = false;
      let statusFilter = {json.dumps(status_filter)};
      let query = new URLSearchParams(window.location.search).get("q") || "";
      let knownIds = [];
      let pollTimer = null;

      const rowsEl = document.getElementById("lazy-rows");
      const statusEl = document.getElementById("list-status");
      const searchEl = document.getElementById("list-search");
      let sentinelEl = document.getElementById("scroll-sentinel");
      const selectAllEl = document.getElementById("select-all");
      let scrollObserver = null;
      let scrollBound = false;
      let liveBannerEl = null;

      function ensureLiveBanner() {{
        if (liveBannerEl) return liveBannerEl;
        liveBannerEl = document.createElement("div");
        liveBannerEl.className = "panel live-banner";
        liveBannerEl.hidden = true;
        liveBannerEl.innerHTML = '<span class="live-banner-text"></span> <button type="button" class="primary">Show updates</button>';
        liveBannerEl.querySelector("button").addEventListener("click", () => {{
          liveBannerEl.hidden = true;
          window.scrollTo({{ top: 0, behavior: "smooth" }});
          loadRows(false);
        }});
        const searchBox = document.querySelector(".search-box");
        if (searchBox && searchBox.parentNode) {{
          searchBox.parentNode.insertBefore(liveBannerEl, searchBox);
        }} else if (rowsEl && rowsEl.parentNode) {{
          rowsEl.parentNode.insertBefore(liveBannerEl, rowsEl);
        }}
        return liveBannerEl;
      }}

      function showLiveBanner(message) {{
        const el = ensureLiveBanner();
        el.querySelector(".live-banner-text").textContent = message;
        el.hidden = false;
      }}

      function idsFromRoot(root) {{
        if (!root) return [];
        return Array.from(root.querySelectorAll(`input[name="${{checkboxName}}"]`)).map((cb) => cb.value);
      }}

      function idsEqual(a, b) {{
        if (a.length !== b.length) return false;
        return a.every((id, i) => id === b[i]);
      }}

      function ensureSentinel() {{
        if (!rowsEl) return null;
        if (!sentinelEl) {{
          sentinelEl = document.createElement("div");
          sentinelEl.id = "scroll-sentinel";
          sentinelEl.className = "scroll-sentinel";
          sentinelEl.setAttribute("aria-hidden", "true");
        }}
        rowsEl.appendChild(sentinelEl);
        return sentinelEl;
      }}

      function tailInView() {{
        const sentinel = ensureSentinel();
        if (!sentinel) return false;
        const rect = sentinel.getBoundingClientRect();
        return rect.top <= window.innerHeight + 320;
      }}

      function maybeLoadMore() {{
        if (hasMore && !loading && tailInView()) {{
          loadRows(true);
        }}
      }}

      function bindInfiniteScroll() {{
        const sentinel = ensureSentinel();
        if (!sentinel || !hasMore) return;

        if ("IntersectionObserver" in window) {{
          if (scrollObserver) scrollObserver.disconnect();
          scrollObserver = new IntersectionObserver(
            (entries) => {{
              if (entries.some((entry) => entry.isIntersecting)) {{
                maybeLoadMore();
              }}
            }},
            {{ root: null, rootMargin: "320px 0px", threshold: 0 }}
          );
          scrollObserver.observe(sentinel);
        }}

        if (!scrollBound) {{
          window.addEventListener("scroll", maybeLoadMore, {{ passive: true }});
          window.addEventListener("resize", maybeLoadMore, {{ passive: true }});
          scrollBound = true;
        }}
      }}

      function stopInfiniteScroll() {{
        if (scrollObserver) {{
          scrollObserver.disconnect();
          scrollObserver = null;
        }}
      }}

      function scheduleTailCheck() {{
        requestAnimationFrame(() => requestAnimationFrame(maybeLoadMore));
      }}

      if (searchEl) {{
        searchEl.value = query;
        let debounce = null;
        searchEl.addEventListener("input", () => {{
          clearTimeout(debounce);
          debounce = setTimeout(() => {{
            query = searchEl.value.trim();
            const url = new URL(window.location.href);
            if (query) url.searchParams.set("q", query); else url.searchParams.delete("q");
            window.history.replaceState({{}}, "", url);
            offset = 0;
            loadRows(false);
          }}, 300);
        }});
      }}

      document.querySelectorAll("[data-status-filter]").forEach((btn) => {{
        btn.addEventListener("click", () => {{
          statusFilter = btn.getAttribute("data-status-filter") || "";
          document.querySelectorAll("[data-status-filter]").forEach((b) => b.classList.remove("primary"));
          btn.classList.add("primary");
          offset = 0;
          loadRows(false);
        }});
      }});

      if (selectAllEl) {{
        selectAllEl.addEventListener("change", (e) => {{
          document.querySelectorAll(`input[name="${{checkboxName}}"]`).forEach((cb) => {{
            cb.checked = e.target.checked;
          }});
        }});
      }}

      function setupInfiniteScroll() {{
        if (hasMore) {{
          bindInfiniteScroll();
          scheduleTailCheck();
        }} else {{
          stopInfiniteScroll();
        }}
      }}

      async function loadRows(append) {{
        if (loading) return;
        loading = true;
        if (!append) {{
          offset = 0;
          hasMore = true;
          rowsEl.innerHTML = '<div class="panel muted">Loading…</div>';
          if (liveBannerEl) liveBannerEl.hidden = true;
        }} else {{
          ensureSentinel()?.classList.add("loading-more");
        }}
        if (!append) statusEl.textContent = "Loading…";
        try {{
          const params = new URLSearchParams({{
            offset: String(append ? offset : 0),
            limit: String(pageSize),
            status: statusFilter,
            q: query,
          }});
          const resp = await fetch(`${{apiPath}}?${{params}}`, {{ credentials: "same-origin" }});
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.error || "load failed");
          if (!append) rowsEl.innerHTML = "";
          if (data.html) {{
            const wrap = document.createElement("div");
            wrap.innerHTML = data.html;
            while (wrap.firstChild) rowsEl.appendChild(wrap.firstChild);
          }} else if (!append) {{
            rowsEl.innerHTML = `<div class="panel muted">${{emptyMessage}}</div>`;
          }}
          offset = data.next_offset || 0;
          hasMore = !!data.has_more;
          if (!append) knownIds = idsFromRoot(rowsEl);
          const loadedCount = rowsEl.querySelectorAll(".incident-row").length;
          const liveHint = " · live";
          statusEl.textContent = (hasMore
            ? `Showing ${{loadedCount}} — scroll for more`
            : `Showing all ${{loadedCount}} matches`) + liveHint;
        }} catch (err) {{
          if (!append) rowsEl.innerHTML = `<div class="panel"><span class="badge severity-critical">${{err.message}}</span></div>`;
          statusEl.textContent = "";
          stopInfiniteScroll();
        }} finally {{
          ensureSentinel()?.classList.remove("loading-more");
          loading = false;
          setupInfiniteScroll();
        }}
      }}

      async function pollForUpdates() {{
        if (document.hidden || loading) return;
        try {{
          const params = new URLSearchParams({{
            offset: "0",
            limit: String(pageSize),
            status: statusFilter,
            q: query,
          }});
          const resp = await fetch(`${{apiPath}}?${{params}}`, {{ credentials: "same-origin" }});
          const data = await resp.json();
          if (!resp.ok) return;
          const wrap = document.createElement("div");
          wrap.innerHTML = data.html || "";
          const freshIds = idsFromRoot(wrap);
          const baseline = knownIds.slice(0, pageSize);
          if (idsEqual(freshIds, baseline)) return;
          const newCount = freshIds.filter((id) => !baseline.includes(id)).length;
          if (window.scrollY < 140) {{
            await loadRows(false);
          }} else {{
            const label = newCount > 0
              ? `${{newCount}} new ${{newCount === 1 ? "item" : "items"}} available`
              : "List updated";
            showLiveBanner(label);
          }}
        }} catch (_err) {{
          // ignore transient poll errors
        }}
      }}

      function startPolling() {{
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollForUpdates, pollMs);
      }}

      document.addEventListener("visibilitychange", () => {{
        if (!document.hidden) pollForUpdates();
      }});

      bindInfiniteScroll();
      loadRows(false);
      startPolling();
    }})();
    </script>
    """


def layout(title: str, body: str, *, nav_active: str = "", public_base: str = "") -> str:
    del public_base  # reserved for future absolute asset/link base
    nav_items = (
        ("incidents", "/", "Incidents"),
        ("alerts", "/alerts", "Alerts"),
        ("new", "/incidents/new", "New"),
        ("settings", "/settings", "Settings"),
    )
    nav_links = []
    for key, href, label in nav_items:
        cls = "active" if key == nav_active else ""
        aria = ' aria-current="page"' if key == nav_active else ""
        nav_links.append(f'<a class="{cls}" href="{href}"{aria}>{_esc(label)}</a>')
    nav_html = "\n      ".join(nav_links)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)} · Hearth</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f1419;
      --panel: #1a2332;
      --panel-2: #243044;
      --text: #e7edf5;
      --muted: #9fb0c3;
      --accent: #e8a45c;
      --ok: #3ecf8e;
      --warn: #f5c451;
      --crit: #ff6b6b;
      --border: #2d3b52;
      --lock: #7a8aa0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font: 15px/1.5 ui-sans-serif, system-ui, sans-serif;
      background: radial-gradient(circle at top, #172033, var(--bg));
      color: var(--text);
      min-height: 100vh;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
    .site-header {{
      display: flex; align-items: flex-end; justify-content: space-between;
      gap: 16px; margin-bottom: 20px; flex-wrap: wrap;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
    }}
    .site-header h1 {{ margin: 0; font-size: 1.35rem; letter-spacing: 0.02em; }}
    .brand-link {{ color: inherit; text-decoration: none; }}
    .brand-link:hover {{ text-decoration: none; color: var(--accent); }}
    .site-nav {{
      display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    }}
    .site-nav a {{
      display: inline-flex; align-items: center; justify-content: center;
      min-height: 36px; padding: 6px 12px;
      border: 1px solid transparent;
      border-radius: 10px;
      color: var(--muted);
      text-decoration: none;
      font-weight: 500;
    }}
    .site-nav a:hover {{
      color: var(--text);
      background: var(--panel);
      text-decoration: none;
    }}
    .site-nav a.active {{
      color: var(--text);
      background: color-mix(in srgb, var(--accent) 22%, var(--panel-2));
      border-color: var(--accent);
    }}
    .page-toolbar {{
      display: flex; gap: 8px; flex-wrap: wrap;
      align-items: center; margin-bottom: 12px;
    }}
    .panel {{
      background: color-mix(in srgb, var(--panel) 92%, transparent);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px;
      margin-bottom: 16px;
      backdrop-filter: blur(8px);
    }}
    .grid {{ display: grid; gap: 12px; }}
    .incident-row {{
      display: grid;
      grid-template-columns: auto 1.4fr 0.7fr 0.7fr 0.8fr auto;
      gap: 12px;
      align-items: center;
      padding: 12px 14px;
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--panel);
    }}
    .incident-row:hover {{ border-color: var(--accent); }}
    .incident-row-head {{
      display: grid;
      grid-template-columns: auto 1.4fr 0.7fr 0.7fr 0.8fr auto;
      gap: 12px;
      align-items: center;
      padding: 0 14px 8px;
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .bulk-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
    }}
    .search-box {{
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
    }}
    .search-box input {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.92rem;
    }}
    .list-status {{ color: var(--muted); font-size: 0.9rem; margin: 8px 0; }}
    .scroll-sentinel {{
      min-height: 4px;
      width: 100%;
      pointer-events: none;
      grid-column: 1 / -1;
    }}
    .scroll-sentinel.loading-more::after {{
      content: "Loading more…";
      display: block;
      text-align: center;
      color: var(--muted);
      font-size: 0.9rem;
      padding: 12px 0 4px;
    }}
    .status-filter {{ cursor: pointer; }}
    .row-check {{ width: 18px; height: 18px; accent-color: var(--accent); }}
    .row-title {{ font-weight: 600; }}
    .flash {{ border-color: color-mix(in srgb, var(--accent) 50%, var(--border)); }}
    .agent-feed {{ display: grid; gap: 10px; max-height: 420px; overflow: auto; }}
    .agent-msg {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      background: var(--panel);
      white-space: pre-wrap;
      font-size: 0.92rem;
    }}
    .agent-msg.user {{ border-color: color-mix(in srgb, var(--accent) 40%, var(--border)); }}
    .agent-msg.assistant {{ border-color: color-mix(in srgb, var(--ok) 35%, var(--border)); }}
    .agent-msg .role {{
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .agent-status {{ color: var(--muted); font-size: 0.9rem; }}
    .muted {{ color: var(--muted); font-size: 0.92rem; }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border: 1px solid var(--border);
      background: var(--panel-2);
    }}
    .status-open {{ color: var(--warn); border-color: color-mix(in srgb, var(--warn) 50%, var(--border)); }}
    .status-acknowledged {{ color: var(--accent); }}
    .status-resolved {{ color: var(--ok); border-color: color-mix(in srgb, var(--ok) 50%, var(--border)); }}
    .status-merged {{ color: var(--muted); }}
    .severity-critical {{ color: var(--crit); }}
    .severity-warning {{ color: var(--warn); }}
    .severity-info {{ color: var(--accent); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .actions form {{ margin: 0; display: inline-flex; }}
    .actions button, .actions .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      min-height: 38px;
      line-height: 1.2;
    }}
    button, .btn {{
      appearance: none;
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 10px;
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
    }}
    button.primary, .btn.primary {{ background: color-mix(in srgb, var(--accent) 25%, var(--panel-2)); border-color: var(--accent); }}
    button.danger {{ border-color: color-mix(in srgb, var(--crit) 50%, var(--border)); }}
    input, textarea, select {{
      width: 100%;
      background: var(--panel);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 10px 12px;
      font: inherit;
    }}
    textarea {{ min-height: 96px; resize: vertical; }}
    .filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
    .timeline {{ display: grid; gap: 10px; }}
    .event {{
      border-left: 2px solid var(--border);
      padding-left: 12px;
    }}
    .alert-card {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      background: var(--panel);
      white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.85rem;
    }}
    .two-col {{ display: grid; gap: 16px; }}
    @media (min-width: 900px) {{ .two-col {{ grid-template-columns: 1.2fr 0.8fr; }} }}
    @media (max-width: 800px) {{
      .incident-row, .incident-row-head {{ grid-template-columns: auto 1fr; }}
    }}
    .lock-badge {{
      display: inline-block;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--lock);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 1px 8px;
      margin-left: 8px;
      vertical-align: middle;
    }}
    .field-locked input, .field-locked textarea, .field-locked select {{
      opacity: 0.75;
      cursor: not-allowed;
    }}
    .setup-banner {{
      border-color: color-mix(in srgb, var(--warn) 45%, var(--border));
      background: color-mix(in srgb, var(--warn) 8%, var(--panel));
    }}
    .integ-status {{
      display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px;
    }}
    .integ-pill {{
      font-size: 0.78rem;
      padding: 2px 10px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--panel-2);
    }}
    .integ-pill.ok {{ color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, var(--border)); }}
    .integ-pill.bad {{ color: var(--crit); border-color: color-mix(in srgb, var(--crit) 40%, var(--border)); }}
    .settings-tabs {{
      display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px;
    }}
    .settings-tabs [role="tab"] {{
      min-height: 36px;
      padding: 6px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--panel);
      color: var(--muted);
    }}
    .settings-tabs [role="tab"]:hover {{ border-color: var(--accent); color: var(--text); }}
    .settings-tabs [role="tab"][aria-selected="true"] {{
      color: var(--text);
      background: color-mix(in srgb, var(--accent) 22%, var(--panel-2));
      border-color: var(--accent);
    }}
    .settings-panel[hidden] {{ display: none !important; }}
    .error-banner {{
      border-color: color-mix(in srgb, var(--crit) 55%, var(--border));
      background: color-mix(in srgb, var(--crit) 10%, var(--panel));
      color: var(--crit);
    }}
    .error-banner ul {{ margin: 8px 0 0; padding-left: 18px; }}
    .error-banner li {{ margin: 4px 0; }}
    .ok-banner {{
      border-color: color-mix(in srgb, var(--ok) 45%, var(--border));
      color: var(--ok);
    }}
    .skill-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px 16px;
      align-items: start;
      padding: 12px 0;
      border-bottom: 1px solid var(--border);
    }}
    .skill-row:last-child {{ border-bottom: 0; }}
    .skill-main {{ min-width: 0; }}
    .skill-actions {{
      display: flex;
      flex-wrap: nowrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      flex-shrink: 0;
    }}
    .skill-actions form {{ display: inline; margin: 0; }}
    .skill-desc {{
      color: var(--muted);
      font-size: 0.92rem;
      margin-top: 4px;
      overflow: hidden;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-clamp: 2;
    }}
    .skill-desc.is-expanded {{
      display: block;
      -webkit-line-clamp: unset;
      line-clamp: unset;
      overflow: visible;
    }}
    .skill-more {{
      background: none;
      border: 0;
      color: var(--accent);
      padding: 0;
      margin-top: 4px;
      cursor: pointer;
      font: inherit;
    }}
    .skill-more:hover {{ text-decoration: underline; }}
    .live-banner {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
      background: color-mix(in srgb, var(--accent) 10%, var(--panel));
    }}
    @media (max-width: 700px) {{
      .skill-row {{ grid-template-columns: 1fr; }}
      .skill-actions {{ justify-content: flex-start; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="site-header">
      <div>
        <h1><a class="brand-link" href="/">Hearth</a></h1>
        <div class="muted">Homelab incident desk</div>
      </div>
      <nav class="site-nav" aria-label="Primary">
      {nav_html}
      </nav>
    </header>
    {body}
  </div>
</body>
</html>"""


def error_page(message: str) -> str:
    body = f"""
    <div class="panel" style="max-width:520px;margin:48px auto;">
      <h2 style="margin-top:0;">{_esc(message)}</h2>
      <p class="muted">Use the navigation above, or <a href="/">return to incidents</a>.</p>
    </div>
    """
    return layout("Error", body, nav_active="incidents")


def incident_list_page(
    *,
    status_filter: str,
    hermes_base: str,
    include_noise: bool = False,
    hidden_summary: str = "",
    flash_message: str = "",
    search_query: str = "",
    setup_hints: list[str] | None = None,
    aiops_errors: list[str] | None = None,
) -> str:
    filters = []
    for status in ("", "open", "acknowledged", "resolved"):
        label = status or "all"
        active = "primary" if status == status_filter else ""
        filters.append(
            f'<button type="button" class="btn status-filter {active}" data-status-filter="{_esc(status)}">{_esc(label)}</button>'
        )

    hidden_note = ""
    if hidden_summary and not include_noise:
        hidden_note = f'<p class="muted">Hidden noise alerts: {_esc(hidden_summary)}. Enable <strong>Show noise</strong> in <a href="/settings">Settings</a>.</p>'
    flash = f'<div class="panel flash">{_esc(flash_message)}</div>' if flash_message else ""
    setup = ""
    if setup_hints:
        items = "".join(f"<li>{_esc(h)}</li>" for h in setup_hints)
        setup = f'<div class="panel setup-banner"><strong>Finish setup</strong><ul style="margin:8px 0 0;padding-left:18px;">{items}</ul><p class="muted" style="margin:10px 0 0;"><a href="/settings">Open Settings</a></p></div>'
    aiops_banner = ""
    if aiops_errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in aiops_errors)
        aiops_banner = (
            f'<div class="panel error-banner"><strong>AIOps configuration error</strong>'
            f"<ul>{items}</ul>"
            f'<p style="margin:10px 0 0;"><a href="/settings#aiops">Fix in Settings → AIOps</a></p></div>'
        )
    return_hidden = f'<input type="hidden" name="return_status" value="{_esc(status_filter)}">'

    body = f"""
    <div class="page-toolbar filters">
      {''.join(filters)}
    </div>
    {flash}
    {aiops_banner}
    {setup}
    {hidden_note}
    <div class="panel search-box">
      <label for="list-search"><strong>Search</strong> <span class="muted">JQL-style, e.g. <code>status:open severity>=warning title~"flux"</code></span></label>
      <input id="list-search" type="search" placeholder="status:open severity>=warning title~&quot;flux&quot;" value="{_esc(search_query)}" autocomplete="off">
      <div id="list-status" class="list-status"></div>
    </div>
    <form method="post" action="/incidents/bulk" class="grid">
      {return_hidden}
      <div class="panel bulk-bar">
        <label class="muted"><input class="row-check" type="checkbox" id="select-all"> Select all</label>
        <div class="actions">
          <button type="submit" name="action" value="ack">Acknowledge</button>
          <button type="submit" name="action" value="resolve">Resolve</button>
          <button type="submit" name="action" value="reopen">Reopen</button>
          <button type="submit" name="action" value="merge" title="Merges into the first selected incident">Merge into first</button>
        </div>
      </div>
      <div class="incident-row-head">
        <span></span><span>Incident</span><span>Status</span><span>Severity</span><span>Updated</span><span></span>
      </div>
      <div id="lazy-rows" class="grid"></div>
    </form>
    {_lazy_list_script(kind="incidents", api_path="/api/list/incidents", status_filter=status_filter, checkbox_name="incident_id", empty_message="No incidents match this search.")}
    """
    return layout("Incidents", body, nav_active="incidents")


def alerts_list_page(
    *,
    status_filter: str,
    flash_message: str = "",
    search_query: str = "",
) -> str:
    filters = []
    for status in ("", "firing", "resolved"):
        label = status or "all"
        active = "primary" if status == status_filter else ""
        filters.append(
            f'<button type="button" class="btn status-filter {active}" data-status-filter="{_esc(status)}">{_esc(label)}</button>'
        )

    flash = f'<div class="panel flash">{_esc(flash_message)}</div>' if flash_message else ""
    return_hidden = f'<input type="hidden" name="return_status" value="{_esc(status_filter)}">'

    body = f"""
    <div class="page-toolbar filters">
      {''.join(filters)}
    </div>
    {flash}
    <p class="muted">Alertmanager → <strong>alerts inbox</strong> → raise incident (manual or auto-raise rules in Settings).</p>
    <div class="panel search-box">
      <label for="list-search"><strong>Search</strong> <span class="muted">JQL-style, e.g. <code>status:firing alertname:Homelab* namespace:flux-system</code></span></label>
      <input id="list-search" type="search" placeholder="status:firing alertname:Homelab* text~&quot;disk&quot;" value="{_esc(search_query)}" autocomplete="off">
      <div id="list-status" class="list-status"></div>
    </div>
    <form method="post" action="/alerts/raise" class="grid">
      {return_hidden}
      <div class="panel bulk-bar">
        <label class="muted"><input class="row-check" type="checkbox" id="select-all"> Select all</label>
        <input name="title" placeholder="Incident title (optional)" style="max-width:280px;">
        <div class="actions">
          <button class="primary" type="submit">Raise incident</button>
        </div>
      </div>
      <div class="incident-row-head">
        <span></span><span>Alert</span><span>Status</span><span>Severity</span><span>Updated</span><span></span>
      </div>
      <div id="lazy-rows" class="grid"></div>
    </form>
    {_lazy_list_script(kind="alerts", api_path="/api/list/alerts", status_filter=status_filter, checkbox_name="fingerprint", empty_message="No alerts match this search.")}
    """
    return layout("Alerts", body, nav_active="alerts")


def create_incident_page(*, error: str = "") -> str:
    err = f'<div class="panel"><span class="badge severity-critical">{_esc(error)}</span></div>' if error else ""
    body = f"""
    {err}
    <div class="panel">
      <h2 style="margin-top:0;">New incident</h2>
      <p class="muted">Create a manual ticket — useful for tracking work that did not come from an alert.</p>
      <form method="post" action="/incidents/new" class="grid">
        <input name="title" placeholder="Title" required autofocus>
        <textarea name="summary" placeholder="What is going on?"></textarea>
        <select name="severity">
          <option value="critical">critical</option>
          <option value="warning" selected>warning</option>
          <option value="info">info</option>
          <option value="unknown">unknown</option>
        </select>
        <input name="tags" placeholder="Tags (comma-separated)">
        <textarea name="note" placeholder="Initial note (optional)"></textarea>
        <div class="actions">
          <button class="primary" type="submit">Create incident</button>
          <a class="btn" href="/">Cancel</a>
        </div>
      </form>
    </div>
    """
    return layout("New incident", body, nav_active="new")


def _agent_panel_script(iid: str, hermes: dict[str, Any], *, auto_investigate: bool = False) -> str:
    session_id = str(hermes.get("session_id") or "")
    stream_id = str(hermes.get("stream_id") or "")
    status = str(hermes.get("status") or "")
    return f"""
    <script>
    (function() {{
      const incidentId = {json.dumps(iid)};
      const sessionId = {json.dumps(session_id)};
      const streamId = {json.dumps(stream_id)};
      const status = {json.dumps(status)};
      const autoInvestigate = {json.dumps(auto_investigate)};
      const feedEl = document.getElementById("agent-feed");
      const statusEl = document.getElementById("agent-status");
      let streamSource = null;

      function renderMessages(messages) {{
        if (!feedEl) return;
        feedEl.innerHTML = "";
        if (!messages || !messages.length) {{
          feedEl.innerHTML = '<div class="muted">No agent messages yet.</div>';
          return;
        }}
        for (const msg of messages) {{
          const role = msg.role || "message";
          const block = document.createElement("div");
          block.className = "agent-msg " + role;
          const roleEl = document.createElement("div");
          roleEl.className = "role";
          roleEl.textContent = role;
          const bodyEl = document.createElement("div");
          bodyEl.textContent = msg.content || "";
          block.appendChild(roleEl);
          block.appendChild(bodyEl);
          feedEl.appendChild(block);
        }}
        feedEl.scrollTop = feedEl.scrollHeight;
      }}

      async function refreshSession() {{
        try {{
          const resp = await fetch("/api/incidents/" + encodeURIComponent(incidentId) + "/agent/session", {{
            credentials: "same-origin",
          }});
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          const data = await resp.json();
          renderMessages(data.messages || []);
          if (statusEl) {{
            statusEl.textContent = data.status === "running"
              ? "Agent is investigating…"
              : (data.messages && data.messages.length ? "Agent session ready" : "Waiting for agent output");
          }}
        }} catch (err) {{
          if (statusEl) statusEl.textContent = "Could not load agent feed: " + err.message;
        }}
      }}

      function connectStream() {{
        if (!streamId || status !== "running") return;
        if (streamSource) streamSource.close();
        streamSource = new EventSource(
          "/api/incidents/" + encodeURIComponent(incidentId) + "/agent/stream?stream_id=" + encodeURIComponent(streamId)
        );
        if (statusEl) statusEl.textContent = "Streaming agent response…";
        streamSource.onmessage = () => refreshSession();
        streamSource.addEventListener("end", () => {{
          streamSource.close();
          refreshSession();
        }});
        streamSource.onerror = () => {{
          streamSource.close();
          refreshSession();
        }};
      }}

      if (autoInvestigate && !sessionId) {{
        window.location.replace("/incidents/" + encodeURIComponent(incidentId) + "/investigate");
        return;
      }}

      if (sessionId) {{
        refreshSession();
        connectStream();
        if (status !== "running") {{
          window.setInterval(refreshSession, 5000);
        }}
      }}
    }})();
    </script>
    """


def incident_detail_page(
    incident: dict[str, Any],
    *,
    hermes_base: str,
    message: str = "",
    auto_investigate: bool = False,
    hermes_enabled: bool = True,
) -> str:
    iid = incident["id"]
    status = str(incident.get("status") or "open")
    tags = (incident.get("enrichment") or {}).get("tags") or []
    notes = (incident.get("enrichment") or {}).get("notes") or []
    merged_into = incident.get("merged_into_id")

    action_buttons = []
    if status == "open":
        action_buttons.append(f'<form method="post" action="/incidents/{_esc(iid)}/ack"><button class="primary" type="submit">Acknowledge</button></form>')
    if status in ("open", "acknowledged"):
        action_buttons.append(f'<form method="post" action="/incidents/{_esc(iid)}/resolve"><button type="submit">Resolve</button></form>')
    if status == "resolved":
        action_buttons.append(f'<form method="post" action="/incidents/{_esc(iid)}/reopen"><button type="submit">Reopen</button></form>')

    hermes = (incident.get("enrichment") or {}).get("hermes") or {}
    hermes_session_id = str(hermes.get("session_id") or "")
    hermes_status = str(hermes.get("status") or "")

    investigate_btn = ""
    if hermes_enabled:
        investigate_btn = (
            f'<form method="post" action="/incidents/{_esc(iid)}/investigate">'
            f'<button class="primary" type="submit">Investigate</button></form>'
        )
        if hermes_session_id:
            investigate_btn += (
                f'<form method="post" action="/incidents/{_esc(iid)}/investigate">'
                f'<input type="hidden" name="force" value="1">'
                f'<button type="submit">New investigation</button></form>'
            )

    hermes_link = ""
    if hermes_enabled and hermes_base and hermes_session_id:
        hermes_url = f"{hermes_base.rstrip('/')}/?session_id={quote(hermes_session_id)}"
        hermes_link = f'<a class="btn" href="{_esc(hermes_url)}" target="_blank" rel="noopener">Open in Hermes</a>'

    agent_status = ""
    if not hermes_enabled:
        agent_status = (
            '<div id="agent-status" class="agent-status">'
            'Hermes integration is disabled. Configure it in <a href="/settings">Settings</a>.'
            "</div>"
        )
    elif hermes_session_id:
        agent_status = f'<div id="agent-status" class="agent-status">Status: {_esc(hermes_status or "unknown")}</div>'
    else:
        agent_status = '<div id="agent-status" class="agent-status">No agent session yet — start an investigation.</div>'

    agent_panel = f"""
    <div class="panel" id="agent">
      <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;">
        <h3 style="margin:0;">Agent</h3>
        <div class="actions">
          {investigate_btn}
          {hermes_link}
        </div>
      </div>
      {agent_status}
      <div id="agent-feed" class="agent-feed" style="margin-top:12px;"></div>
    </div>
    {_agent_panel_script(iid, hermes, auto_investigate=auto_investigate)}
    """

    alert_cards = []
    for alert in incident.get("alerts") or []:
        labels = alert.get("labels") or {}
        title = labels.get("alertname", "alert")
        alert_cards.append(
            f"""
            <div class="alert-card">
              <div><strong>{_esc(title)}</strong> · {_esc(alert.get('status'))}</div>
              <div class="muted">fingerprint: {_esc(alert.get('fingerprint'))}</div>
              <div>{_esc((alert.get('annotations') or {}).get('description') or (alert.get('annotations') or {}).get('summary') or '')}</div>
            </div>
            """
        )

    events = []
    for event in incident.get("events") or []:
        detail = event.get("detail") or {}
        extra = ""
        if event.get("event_type") == "note_added":
            extra = _esc(detail.get("body", ""))
        elif event.get("event_type") == "merged":
            extra = f"into {_esc(detail.get('into', ''))}"
        events.append(
            f"""
            <div class="event">
              <div><strong>{_esc(event.get('event_type'))}</strong> <span class="muted">{_esc(event.get('created_at'))}</span></div>
              <div class="muted">{_esc(event.get('actor') or 'system')} {extra}</div>
            </div>
            """
        )

    note_items = []
    for note in notes:
        note_items.append(
            f'<div class="event"><div>{_esc(note.get("body"))}</div><div class="muted">{_esc(note.get("actor"))} · {_esc(note.get("created_at"))}</div></div>'
        )

    msg = f'<div class="panel">{_esc(message)}</div>' if message else ""
    merged_banner = ""
    if merged_into:
        merged_banner = f'<div class="panel">Merged into <a href="/incidents/{_esc(merged_into)}">{_esc(merged_into)}</a></div>'

    tag_str = ", ".join(_esc(t) for t in tags)
    manual_badge = '<span class="badge">manual</span>' if (incident.get("enrichment") or {}).get("manual") else ""

    body = f"""
    {msg}
    {merged_banner}
    <div class="panel">
      <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;">
        <div>
          <h2 style="margin:0 0 8px;">{_esc(incident.get('title') or iid)}</h2>
          <div class="muted">{_esc(iid)} · updated {_esc(incident.get('updated_at'))}</div>
          <div style="margin-top:8px;">{_status_badge(status)} {_severity_badge(incident.get('severity'))} {manual_badge}</div>
        </div>
        <div class="actions">
          {''.join(action_buttons)}
        </div>
      </div>
      {f'<p>{_esc(incident.get("summary") or "")}</p>' if incident.get("summary") else ''}
      {f'<p class="muted">Tags: {tag_str}</p>' if tags else ''}
    </div>

    {agent_panel}

    <div class="two-col">
      <div class="panel">
        <h3>Alerts ({len(incident.get('alerts') or [])})</h3>
        <div class="grid">{''.join(alert_cards) or '<div class="muted">No alerts attached.</div>'}</div>
      </div>
      <div class="grid">
        <div class="panel">
          <h3>Enrich</h3>
          <form method="post" action="/incidents/{_esc(iid)}/enrich" class="grid">
            <input name="title" placeholder="Title" value="{_esc(incident.get('title') or '')}">
            <textarea name="summary" placeholder="Summary">{_esc(incident.get('summary') or '')}</textarea>
            <select name="severity">
              {''.join(f'<option value="{_esc(s)}" {"selected" if incident.get("severity")==s else ""}>{_esc(s)}</option>' for s in ("critical", "warning", "info", "unknown"))}
            </select>
            <input name="tags" placeholder="Tags (comma-separated)" value="{_esc(", ".join(tags))}">
            <button class="primary" type="submit">Save</button>
          </form>
        </div>
        <div class="panel">
          <h3>Add note</h3>
          <form method="post" action="/incidents/{_esc(iid)}/notes" class="grid">
            <textarea name="body" placeholder="What did you try? What worked?" required></textarea>
            <button type="submit">Add note</button>
          </form>
        </div>
        <div class="panel">
          <h3>Merge into this incident</h3>
          <form method="post" action="/incidents/{_esc(iid)}/merge" class="grid">
            <input name="source_ids" placeholder="Source incident IDs (comma-separated)" required>
            <button type="submit">Merge</button>
          </form>
        </div>
      </div>
    </div>

    <div class="two-col">
      <div class="panel">
        <h3>Timeline</h3>
        <div class="timeline">{''.join(events) or '<div class="muted">No events yet.</div>'}</div>
      </div>
      <div class="panel">
        <h3>Notes</h3>
        <div class="timeline">{''.join(note_items) or '<div class="muted">No notes yet.</div>'}</div>
      </div>
    </div>
    """
    return layout(incident.get("title") or iid, body, nav_active="incidents")


def _field_lock_badge(field: dict[str, Any]) -> str:
    if field.get("locked"):
        env = field.get("env") or "ENV"
        return f'<span class="lock-badge" title="Set by {_esc(env)}">env</span>'
    return ""


def _bool_toggle(name: str, field: dict[str, Any], *, label: str | None = None, hint: str | None = None) -> str:
    val = field.get("raw_value")
    if val is None:
        val = field.get("value")
    checked = "checked" if val else ""
    disabled = "disabled" if field.get("locked") else ""
    wrap = "field-locked" if field.get("locked") else ""
    return f"""
    <label class="event-toggle {wrap}">
      <input type="checkbox" name="{_esc(name)}" {checked} {disabled}>
      <span>
        <strong>{_esc(label or field.get("label") or name)}</strong>{_field_lock_badge(field)}
        <br><span class="muted">{_esc(hint or field.get("hint") or "")}</span>
      </span>
    </label>
    """


def _text_input(
    name: str,
    field: dict[str, Any],
    *,
    input_name: str | None = None,
    multiline: bool = False,
    placeholder: str = "",
) -> str:
    locked = bool(field.get("locked"))
    wrap = "field-locked" if locked else ""
    disabled = "disabled" if locked else ""
    value = field.get("value") or ""
    fname = input_name or name
    label = field.get("label") or name
    hint = field.get("hint") or ""
    if field.get("secret") and locked:
        value = field.get("value") or "••••"
    if multiline:
        control = (
            f'<textarea name="{_esc(fname)}" placeholder="{_esc(placeholder)}" {disabled}>'
            f"{_esc(value)}</textarea>"
        )
    else:
        typ = "password" if field.get("secret") and not locked else "text"
        ph = "leave blank to keep" if field.get("secret") and not locked else placeholder
        control = (
            f'<input type="{typ}" name="{_esc(fname)}" value="{_esc("" if field.get("secret") and not locked else value)}" '
            f'placeholder="{_esc(ph)}" {disabled}>'
        )
    return f"""
    <div class="{wrap}">
      <label><strong>{_esc(label)}</strong>{_field_lock_badge(field)}</label>
      <div class="muted" style="margin:4px 0 8px;">{_esc(hint)}</div>
      {control}
    </div>
    """


def settings_page(
    config: Any,
    registry: Any,
    *,
    flash_message: str = "",
) -> str:
    flash = f'<div class="panel flash">{_esc(flash_message)}</div>' if flash_message else ""
    groups = config.snapshot()
    statuses = {row["id"]: row for row in registry.status_summary(probe=False)}
    hermes = registry.hermes()
    aiops_on = bool(config.aiops_enabled())
    aiops_errors = hermes.connection_errors() if aiops_on else []
    aiops_connected = aiops_on and not aiops_errors
    env_found = config.hydrate_aiops_from_env() if aiops_on else {}
    skills: list[dict[str, Any]] = []
    memory: dict[str, Any] = {}
    admin_error = ""
    if aiops_connected:
        try:
            client = hermes.client()
            skills = client.list_skills()
            memory = client.get_memory()
        except Exception as exc:
            admin_error = str(exc)
            aiops_connected = False
            aiops_errors = aiops_errors + [admin_error]

    def g(group: str, key: str) -> dict[str, Any]:
        for item in groups.get(group) or []:
            if item["key"] == key:
                return item
        return {"key": key, "value": "", "locked": False, "label": key, "hint": "", "raw_value": None}

    def _configured(integ_id: str) -> bool:
        if integ_id == "prometheus":
            return bool(config.get_bool("prometheus.enabled"))
        if integ_id == "ntfy":
            return bool(config.get_str("ntfy.base_url"))
        if integ_id == "hermes":
            return hermes.is_connected()
        return False

    def status_pills() -> str:
        pills = []
        for integ in registry.all():
            st = statuses.get(integ.meta.id) or {}
            enabled = bool(st.get("enabled"))
            configured = _configured(integ.meta.id)
            name = "AIOps" if integ.meta.id == "hermes" else integ.meta.name
            if not enabled:
                cls, label = "", f"{name}: off"
            elif configured:
                cls, label = "ok", f"{name}: connected"
            else:
                cls, label = "bad", f"{name}: needs config"
            pills.append(f'<span class="integ-pill {cls}">{_esc(label)}</span>')
        return f'<div class="integ-status">{"".join(pills)}</div>'

    def _skills_panel() -> str:
        if not aiops_on:
            return ""
        if not aiops_connected:
            return ""
        rows = []
        for skill in skills:
            name = str(skill.get("name") or "")
            desc = str(skill.get("description") or skill.get("category") or "")
            enabled = skill.get("enabled", True)
            toggle_to = "false" if enabled else "true"
            toggle_label = "Disable" if enabled else "Enable"
            more_btn = ""
            if len(desc) > 140:
                more_btn = (
                    '<button type="button" class="skill-more" data-skill-more>'
                    "Read more</button>"
                )
            rows.append(
                f"""
                <div class="skill-row">
                  <div class="skill-main">
                    <strong>{_esc(name)}</strong>
                    <span class="badge {"status-resolved" if enabled else "status-merged"}">{"on" if enabled else "off"}</span>
                    <div class="skill-desc">{_esc(desc)}</div>
                    {more_btn}
                  </div>
                  <div class="skill-actions">
                    <form method="post" action="/settings/aiops/skills/toggle">
                      <input type="hidden" name="name" value="{_esc(name)}">
                      <input type="hidden" name="enabled" value="{toggle_to}">
                      <button type="submit">{_esc(toggle_label)}</button>
                    </form>
                    <form method="post" action="/settings/aiops/skills/delete" onsubmit="return confirm('Delete skill {_esc(name)}?');">
                      <input type="hidden" name="name" value="{_esc(name)}">
                      <button type="submit">Delete</button>
                    </form>
                  </div>
                </div>
                """
            )
        skill_list = "\n".join(rows) if rows else '<p class="muted">No skills found on Hermes yet.</p>'
        return f"""
        <div class="settings-panel" data-panel="aiops-skills" id="aiops-skills" role="tabpanel" hidden>
          <div class="panel">
            <h2 style="margin-top:0;">Skills</h2>
            <p class="muted">Managed on Hermes via API — create, toggle, or delete from Hearth.</p>
            {skill_list}
            <h3>Create / update skill</h3>
            <form method="post" action="/settings/aiops/skills/save" class="grid">
              <input name="name" placeholder="skill-name" required>
              <input name="category" placeholder="category (optional)">
              <textarea name="content" placeholder="SKILL.md content" rows="8" required></textarea>
              <div class="actions"><button class="primary" type="submit">Save skill</button></div>
            </form>
          </div>
        </div>
        """

    def _memory_panel() -> str:
        if not aiops_on or not aiops_connected:
            return ""
        sections = (
            ("soul", "SOUL.md", memory.get("soul") or ""),
            ("user", "USER.md", memory.get("user") or ""),
            ("memory", "MEMORY.md", memory.get("memory") or ""),
        )
        blocks = []
        for key, label, content in sections:
            blocks.append(
                f"""
                <form method="post" action="/settings/aiops/memory" class="grid" style="margin-bottom:16px;">
                  <input type="hidden" name="memory_section" value="{_esc(key)}">
                  <label><strong>{_esc(label)}</strong></label>
                  <textarea name="content" rows="10">{_esc(content)}</textarea>
                  <div class="actions"><button class="primary" type="submit">Save {_esc(label)}</button></div>
                </form>
                """
            )
        return f"""
        <div class="settings-panel" data-panel="aiops-memory" id="aiops-memory" role="tabpanel" hidden>
          <div class="panel">
            <h2 style="margin-top:0;">Memory &amp; persona</h2>
            <p class="muted">Edit Hermes SOUL / USER / MEMORY files through the WebUI API.</p>
            {''.join(blocks)}
          </div>
        </div>
        """

    raise_settings = config.raise_settings()
    alertnames = ", ".join(raise_settings.get("alertnames") or [])
    label_rules = json.dumps(raise_settings.get("label_rules") or [], indent=2)
    ntfy = config.ntfy_settings()
    events = ntfy.get("events") or {}

    aiops_status_html = ""
    if aiops_on and aiops_errors:
        items = "".join(f"<li>{_esc(e)}</li>" for e in aiops_errors)
        aiops_status_html = f'<div class="panel error-banner"><strong>AIOps is enabled but not ready</strong><ul>{items}</ul></div>'
    elif aiops_on and aiops_connected:
        env_note = ""
        if env_found:
            env_note = f'<p class="muted">Env applied: {_esc(", ".join(sorted(env_found.values())))}</p>'
        aiops_status_html = f'<div class="panel ok-banner"><strong>AIOps connected</strong>{env_note}</div>'

    def event_checkbox(name: str, label: str, hint: str) -> str:
        field = g("ntfy", f"ntfy.events.{name}")
        checked = "checked" if events.get(name, False) else ""
        disabled = "disabled" if field.get("locked") else ""
        wrap = "field-locked" if field.get("locked") else ""
        return f"""
        <label class="event-toggle {wrap}">
          <input type="checkbox" name="event_{_esc(name)}" {checked} {disabled}>
          <span><strong>{_esc(label)}</strong>{_field_lock_badge(field)}<br><span class="muted">{_esc(hint)}</span></span>
        </label>
        """

    ignored_names = g("prometheus", "prometheus.ignored_alertnames")
    ignored_rules = g("prometheus", "prometheus.ignored_alert_rules")

    skills_tab = (
        '<button type="button" role="tab" data-tab="aiops-skills" aria-selected="false">Skills</button>'
        if aiops_connected
        else ""
    )
    memory_tab = (
        '<button type="button" role="tab" data-tab="aiops-memory" aria-selected="false">Memory</button>'
        if aiops_connected
        else ""
    )

    body = f"""
    {flash}
    {status_pills()}
    <p class="muted">
      Fields marked <span class="lock-badge">env</span> are set by environment variables and cannot be edited here
      (Grafana-style). Unset env keys are editable and stored on the data volume.
    </p>

    <div class="settings-tabs" role="tablist" aria-label="Settings sections">
      <button type="button" role="tab" data-tab="general" aria-selected="true">General</button>
      <button type="button" role="tab" data-tab="integrations" aria-selected="false">Integrations</button>
      <button type="button" role="tab" data-tab="aiops" aria-selected="false">AIOps</button>
      {skills_tab}
      {memory_tab}
      <button type="button" role="tab" data-tab="auto-raise" aria-selected="false">Auto-raise</button>
      <button type="button" role="tab" data-tab="display" aria-selected="false">Display</button>
    </div>

    <div class="settings-panel" data-panel="general" id="general" role="tabpanel">
      <div class="panel">
        <h2 style="margin-top:0;">General</h2>
        <form method="post" action="/settings" class="grid">
          <input type="hidden" name="section" value="core">
          {_text_input("incidents_public_base_url", g("core", "core.incidents_public_base_url"), input_name="incidents_public_base_url", placeholder="https://incidents.example.com")}
          {_text_input("grafana_public_url", g("core", "core.grafana_public_url"), input_name="grafana_public_url")}
          {_text_input("default_runbook_url", g("core", "core.default_runbook_url"), input_name="default_runbook_url")}
          {_text_input("incidents_auth_token", g("core", "core.incidents_auth_token"), input_name="incidents_auth_token")}
          {_text_input("triage_auth_token", g("core", "core.triage_auth_token"), input_name="triage_auth_token")}
          <div class="actions"><button class="primary" type="submit">Save general</button></div>
        </form>
      </div>
    </div>

    <div class="settings-panel" data-panel="integrations" id="integrations" role="tabpanel" hidden>
      <div class="panel">
        <h2 style="margin-top:0;">Prometheus</h2>
        <p class="muted">{_esc(registry.prometheus().meta.description)}</p>
        <form method="post" action="/settings" class="grid">
          <input type="hidden" name="section" value="prometheus">
          {_bool_toggle("prometheus_enabled", g("prometheus", "prometheus.enabled"))}
          {_text_input("ignored_alertnames", ignored_names, input_name="ignored_alertnames", placeholder="ExtraAlert, OtherNoise")}
          {_text_input("ignored_alert_rules", ignored_rules, input_name="ignored_alert_rules", multiline=True, placeholder='[{{"alertname":"Foo"}}]')}
          <div class="actions">
            <button class="primary" type="submit">Save Prometheus</button>
            <button formaction="/settings/test/prometheus" formmethod="post" type="submit">Test connection</button>
          </div>
        </form>
      </div>

      <div class="panel">
        <h2 style="margin-top:0;">ntfy</h2>
        <p class="muted">{_esc(registry.ntfy().meta.description)}</p>
        <form method="post" action="/settings" class="grid">
          <input type="hidden" name="section" value="ntfy">
          {_bool_toggle("enabled", g("ntfy", "ntfy.enabled"), label="Notifications enabled")}
          {_text_input("base_url", g("ntfy", "ntfy.base_url"), input_name="base_url", placeholder="http://ntfy:80")}
          {_text_input("topic", g("ntfy", "ntfy.topic"), input_name="topic")}
          {_text_input("public_url", g("ntfy", "ntfy.public_url"), input_name="public_url")}
          <div class="panel" style="margin:0;">
            <h3 style="margin-top:0;">Notify on</h3>
            <div class="grid">
              {event_checkbox("created", "New incident", "Incident raised from alert(s) or manual create")}
              {event_checkbox("updated", "Incident updated", "More alerts attached or severity changes")}
              {event_checkbox("resolved", "Resolved", "All alerts cleared or you resolve from UI")}
              {event_checkbox("reopened", "Reopened", "Firing alert returns after resolve")}
              {event_checkbox("manual", "Manual incident", "You create a ticket without alerts")}
              {event_checkbox("acknowledged", "Acknowledged", "Ack from UI or bulk actions")}
              {event_checkbox("merged", "Merged", "Incidents combined in UI")}
            </div>
          </div>
          <div class="actions">
            <button class="primary" type="submit">Save ntfy</button>
            <button formaction="/settings/test/ntfy" formmethod="post" type="submit">Test connection</button>
          </div>
        </form>
      </div>
    </div>

    <div class="settings-panel" data-panel="aiops" id="aiops" role="tabpanel" hidden>
      <div class="panel">
        <h2 style="margin-top:0;">AIOps</h2>
        <p class="muted">
          Optional Hermes module for investigations, skills, and memory.
          When enabled, Hearth reads Hermes env vars (<code>HERMES_*</code> / <code>HEARTH_AIOPS_ENABLED</code>)
          and keeps those fields locked.
        </p>
        {aiops_status_html}
        <form method="post" action="/settings" class="grid">
          <input type="hidden" name="section" value="aiops">
          {_bool_toggle("hermes_enabled", g("hermes", "hermes.enabled"), label="Enable AIOps")}
          {_bool_toggle("auto_triage", g("hermes", "hermes.auto_triage"), label="Auto-triage", hint="Start a Hermes investigation on create and on reopen (fresh chat each time)")}
          {_text_input("webui_url", g("hermes", "hermes.webui_url"), input_name="webui_url")}
          {_text_input("webui_password", g("hermes", "hermes.webui_password"), input_name="webui_password")}
          {_text_input("workspace", g("hermes", "hermes.workspace"), input_name="workspace")}
          {_text_input("public_base_url", g("hermes", "hermes.public_base_url"), input_name="public_base_url")}
          <details>
            <summary class="muted" style="cursor:pointer;">Advanced — legacy webhook triage</summary>
            <div class="grid" style="margin-top:12px;">
              {_text_input("webhook_url", g("hermes", "hermes.webhook_url"), input_name="webhook_url")}
              {_text_input("webhook_secret", g("hermes", "hermes.webhook_secret"), input_name="webhook_secret")}
            </div>
          </details>
          <div class="actions">
            <button class="primary" type="submit">Save AIOps</button>
            <button formaction="/settings/test/hermes" formmethod="post" type="submit">Test connection</button>
          </div>
        </form>
      </div>
    </div>
    {_skills_panel()}
    {_memory_panel()}

    <div class="settings-panel" data-panel="auto-raise" id="auto-raise" role="tabpanel" hidden>
      <div class="panel">
        <h2 style="margin-top:0;">Auto-raise rules</h2>
        <p class="muted">
          Alertmanager webhooks land in the <strong>alerts inbox</strong> first.
          Matching rules automatically raise an incident and attach the alert.
        </p>
        <form method="post" action="/settings" class="grid">
          <input type="hidden" name="section" value="auto_raise">
          {_bool_toggle("raise_enabled", g("auto_raise", "auto_raise.enabled"), label="Auto-raise enabled")}
          {_bool_toggle("group_open", g("auto_raise", "auto_raise.group_open"), label="Group into open incidents")}
          <label><strong>Minimum severity</strong></label>
          <select name="min_severity">
            {''.join(f'<option value="{_esc(s)}" {"selected" if raise_settings.get("min_severity")==s else ""}>{_esc(s)} and above</option>' for s in ("critical", "warning", "info", "unknown"))}
          </select>
          <input name="alertnames" placeholder="Alertnames only (comma-separated, empty = all)" value="{_esc(alertnames)}">
          <textarea name="label_rules" placeholder='Label rules JSON e.g. [{{"alertname":"Foo","namespace":"bar"}}]'>{_esc(label_rules)}</textarea>
          <div class="actions"><button class="primary" type="submit">Save auto-raise</button></div>
        </form>
      </div>
    </div>

    <div class="settings-panel" data-panel="display" id="display" role="tabpanel" hidden>
      <div class="panel">
        <h2 style="margin-top:0;">Display</h2>
        <form method="post" action="/settings" class="grid">
          <input type="hidden" name="section" value="display">
          {_bool_toggle("show_noise", g("display", "display.show_noise"))}
          <div class="actions"><button class="primary" type="submit">Save display</button></div>
        </form>
      </div>
    </div>
    <style>
      .event-toggle {{
        display: flex;
        gap: 12px;
        align-items: flex-start;
        padding: 10px 0;
        border-bottom: 1px solid var(--border);
      }}
      .event-toggle:last-child {{ border-bottom: 0; }}
      .event-toggle input {{ width: auto; margin-top: 4px; }}
      details {{ border-top: 1px solid var(--border); padding-top: 12px; }}
    </style>
    <script>
    (function() {{
      const tabs = Array.from(document.querySelectorAll('.settings-tabs [role="tab"]'));
      const panels = Array.from(document.querySelectorAll(".settings-panel[data-panel]"));
      if (!tabs.length || !panels.length) return;

      function showTab(id, pushHash) {{
        const available = new Set(tabs.map((t) => t.getAttribute("data-tab")));
        const target = available.has(id) ? id : (tabs[0].getAttribute("data-tab") || "general");
        for (const tab of tabs) {{
          const on = tab.getAttribute("data-tab") === target;
          tab.setAttribute("aria-selected", on ? "true" : "false");
        }}
        for (const panel of panels) {{
          panel.hidden = panel.getAttribute("data-panel") !== target;
        }}
        if (pushHash) {{
          history.replaceState(null, "", "#" + target);
        }}
      }}

      for (const tab of tabs) {{
        tab.addEventListener("click", () => showTab(tab.getAttribute("data-tab"), true));
      }}

      document.querySelectorAll("[data-skill-more]").forEach((btn) => {{
        btn.addEventListener("click", () => {{
          const desc = btn.parentElement && btn.parentElement.querySelector(".skill-desc");
          if (!desc) return;
          const open = desc.classList.toggle("is-expanded");
          btn.textContent = open ? "Show less" : "Read more";
        }});
      }});

      const hash = (location.hash || "").replace(/^#/, "");
      showTab(hash || "general", false);
      window.addEventListener("hashchange", () => {{
        showTab((location.hash || "").replace(/^#/, "") || "general", false);
      }});
    }})();
    </script>
    """
    return layout("Settings", body, nav_active="settings")
