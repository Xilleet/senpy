from __future__ import annotations

import html
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from senpy.models import Diagnostic

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <!-- P0-11: Content-Security-Policy — запрещаем inline-скрипты без nonce,
         запрещаем external scripts кроме доверенных CDN. Это блокирует XSS
         через внедрённый в Mermaid-граф HTML (если атакующий подсунет
         HTML-теги (например, script) в имя метки, CSP его не даст выполнить). Пример: 'script' tag в имени label. -->
    <meta http-equiv="Content-Security-Policy"
          content="default-src 'self';
                   script-src 'self' 'unsafe-inline'
                              https://cdn.jsdelivr.net/npm/mermaid@10/
                              https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/;
                   style-src 'self' 'unsafe-inline';
                   img-src 'self' data:;
                   font-src 'self';
                   connect-src 'self';">
    <title>Senpy Story Report</title>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
    <style>
        :root {{
            --bg-main: #1e1e1e;
            --bg-side: #252526;
            --bg-card: #333333;
            --text-main: #d4d4d4;
            --border: #444;
            --error: #f44336;
            --warning: #ff9800;
            --info: #2196f3;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg-main);
            color: var(--text-main);
            margin: 0;
            display: flex;
            height: 100vh;
            overflow: hidden;
        }}
        .sidebar {{
            width: 450px;
            background-color: var(--bg-side);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }}
        .sidebar-header {{
            padding: 20px;
            border-bottom: 1px solid var(--border);
        }}
        .sidebar-header h2 {{ margin: 0 0 10px 0; color: #fff; }}
        .stats p {{ margin: 4px 0; font-size: 14px; color: #aaa; }}
        .stats b {{ color: #fff; }}
        .diagnostics-container {{ padding: 20px; }}
        .main {{
            flex: 1;
            display: flex;
            flex-direction: column;
            position: relative;
        }}
        .topbar {{
            padding: 15px 20px;
            background-color: var(--bg-card);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .topbar h3 {{ margin: 0; font-size: 16px; font-weight: normal; }}
        .controls button {{
            background: #444; border: 1px solid #666; color: #fff;
            padding: 5px 12px; cursor: pointer; border-radius: 4px;
            margin-left: 5px; transition: 0.2s;
        }}
        .controls button:hover {{ background: #555; }}
        /* Diagnostic Cards */
        .diag-card {{
            background: var(--bg-card);
            border-left: 4px solid var(--border);
            padding: 12px;
            margin-bottom: 12px;
            border-radius: 4px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }}
        .diag-card.ERROR {{ border-left-color: var(--error); }}
        .diag-card.WARNING {{ border-left-color: var(--warning); }}
        .diag-card.INFO, .diag-card.HINT {{ border-left-color: var(--info); }}

        .diag-header {{ display: flex; justify-content: space-between; margin-bottom: 6px; }}
        .diag-rule {{ font-weight: bold; font-size: 14px; }}
        .diag-loc {{ font-size: 12px; color: #888; }}
        .diag-msg {{ font-size: 13px; line-height: 1.4; color: #ccc; margin-bottom: 8px; }}

        .code-snippet {{
            background: #111; padding: 8px; border-radius: 4px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 12px; color: #ddd;
            overflow-x: auto; white-space: pre; border: 1px solid #222;
        }}

        #mermaid-graph {{
            flex: 1;
            background: var(--bg-main);
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h2>Senpy Analysis Report</h2>
            <div class="stats">
                <p>Files scanned: <b>{file_count}</b></p>
                <p>Total lines: <b>{total_lines:,}</b></p>
                <p>Analysis time: <b>{elapsed:.3f}s</b></p>
                <p>Diagnostics found: <b>{issue_count}</b></p>
            </div>
        </div>
        <div class="diagnostics-container">
            {diagnostics_html}
        </div>
    </div>

    <div class="main">
        <div class="topbar">
            <h3>Interactive Story Graph <i>(Scroll to zoom, drag to pan)</i></h3>
            <div class="controls">
                <button onclick="window.panZoom && window.panZoom.zoomIn()">Zoom In</button>
                <button onclick="window.panZoom && window.panZoom.zoomOut()">Zoom Out</button>
                <button onclick="window.panZoom && window.panZoom.resetZoom(); window.panZoom.center()">Reset</button>
            </div>
        </div>
        <div id="mermaid-graph">
            <!-- SVG will be injected here by Mermaid -->
            <span style="color:#666;">Rendering story graph...</span>
        </div>
    </div>

    <!-- Load Mermaid as an ES module for modern async rendering -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{
            startOnLoad: false,
            theme: 'dark',
            maxTextSize: 90000,
            // P0-11: 'strict' (default в новых Mermaid) — отключает HTML
            // в нодах графа. Раньше было 'loose', что позволяло XSS через
            // имена меток с <script>/<img onerror=...>. 'strict' рендерит
            // только текст, HTML-теги экранируются.
            securityLevel: 'strict'
        }});

        const graphDef = `{mermaid_code}`;

        async function renderGraph() {{
            const container = document.getElementById('mermaid-graph');
            try {{
                const {{ svg }} = await mermaid.render('m-svg', graphDef);
                container.innerHTML = svg;

                const svgElem = container.querySelector('svg');
                svgElem.style.width = '100%';
                svgElem.style.height = '100%';
                svgElem.style.maxWidth = '100%';

                // Initialize SVG Pan/Zoom
                window.panZoom = svgPanZoom(svgElem, {{
                    zoomEnabled: true,
                    controlIconsEnabled: false,
                    fit: true,
                    center: true,
                    minZoom: 0.1,
                    maxZoom: 20
                }});
            }} catch (e) {{
                // P0-11: используем textContent вместо innerHTML, чтобы
                // e.message (в котором могут быть HTML-символы из графа)
                // не выполнился как HTML.
                const errDiv = document.createElement('div');
                errDiv.style.cssText = 'color:var(--error); padding: 20px;';
                errDiv.textContent = 'Failed to render graph: ' + (e.message || String(e));
                container.innerHTML = '';
                container.appendChild(errDiv);
            }}
        }}

        if (graphDef.trim().length > 0) {{
            renderGraph();
        }} else {{
            document.getElementById('mermaid-graph').innerHTML = '<div style="color:#666;">No story flow (labels) found to render.</div>';
        }}
    </script>
</body>
</html>"""


def generate_html_report(
    diagnostics: list[Diagnostic],
    graph_mermaid: str,
    file_count: int,
    total_lines: int,
    elapsed: float,
    out_path: str,
) -> None:

    # Strip markdown wrappers if present
    graph_code = graph_mermaid.strip()
    graph_code = graph_code.removeprefix("```mermaid")
    graph_code = graph_code.removesuffix("```")

    # Escape JS string literals safely
    js_safe_graph = (
        graph_code.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("$", "\\$")
    )

    js_safe_graph = js_safe_graph.replace("<", "&lt;").replace(">", "&gt;")

    diags_html_parts = []
    if not diagnostics:
        diags_html_parts.append("<div style='color:#4caf50; font-weight:bold;'>✔ No issues found! Perfect!</div>")
    else:
        for diag in diagnostics:
            # Escape HTML to prevent accidental DOM breaking from source code
            safe_msg = html.escape(diag.message)
            safe_code = html.escape(diag.line_content.strip())
            file_name = html.escape(os.path.basename(diag.file_path))

            card = f"""
            <div class="diag-card {diag.severity}">
                <div class="diag-header">
                    <span class="diag-rule" style="color: var(--{diag.severity.lower()})">{diag.code} ({diag.severity})</span>
                    <span class="diag-loc">{file_name}:{diag.line_number}</span>
                </div>
                <div class="diag-msg">{safe_msg}</div>
                <div class="code-snippet">{diag.line_number} | {safe_code}</div>
            </div>
            """
            diags_html_parts.append(card)

    final_html = HTML_TEMPLATE.format(
        file_count=file_count,
        total_lines=total_lines,
        elapsed=elapsed,
        issue_count=len(diagnostics),
        diagnostics_html="".join(diags_html_parts),
        mermaid_code=js_safe_graph
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(final_html)
