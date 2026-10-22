import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';
import * as cp from 'child_process';

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
    const config = vscode.workspace.getConfiguration("senpy");
    let serverCmd = config.get<string>("executablePath") || "senpy";

    // 1. Инициализация LSP Сервера
    const serverOptions: ServerOptions = {
        run: { command: serverCmd, args: ["--lsp"] },
        debug: { command: serverCmd, args: ["--lsp"] }
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: "file", language: "renpy" }]
    };

    client = new LanguageClient(
        "senpyLsp",
        "Senpy Language Server",
        serverOptions,
        clientOptions
    );

    client.start();

    // 2. Команда: Генерация и показ интерактивного графа
    let graphCmd = vscode.commands.registerCommand('senpy.showStoryGraph', async () => {
        if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
            vscode.window.showErrorMessage("Senpy: Please open a Ren'Py project folder first.");
            return;
        }

        const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Senpy: Generating Story Flow Graph...",
            cancellable: false
        }, async () => {
            return new Promise<void>((resolve, reject) => {
                cp.exec(`"${serverCmd}" "${workspaceRoot}" --graph`, { cwd: workspaceRoot, maxBuffer: 1024 * 1024 * 15, timeout: 60000 }, (error, stdout, stderr) => {
                    if (error) {
                        vscode.window.showErrorMessage(`Senpy Graph Error: ${stderr || error.message}`);
                        reject();
                        return;
                    }

                    // 1. Извлекаем Mermaid граф
                    const mermaidMatch = stdout.match(/```mermaid\s*([\s\S]*?)\s*```/);
                    let graphText = mermaidMatch ? mermaidMatch[1].trim() : stdout.trim();

                    // 2. Извлекаем метаданные координат узлов
                    const metaMatch = stdout.match(/```senpy-meta\s*([\s\S]*?)\s*```/);
                    let metaJson = metaMatch ? metaMatch[1].trim() : "{}";

                    if (!graphText || graphText.length === 0) {
                        vscode.window.showWarningMessage("Senpy: No story labels found to build a graph.");
                        resolve();
                        return;
                    }

                    const panel = vscode.window.createWebviewPanel(
                        'senpyGraph',
                        'Story Flow Graph',
                        vscode.ViewColumn.Beside,
                        { 
                            enableScripts: true, 
                            retainContextWhenHidden: true 
                        }
                    );

                    // Обработка клика по узлу из Webview
                    panel.webview.onDidReceiveMessage(async (message) => {
                        if (message.command === 'openLocation') {
                            try {
                                const fileUri = vscode.Uri.file(message.file);
                                const doc = await vscode.workspace.openTextDocument(fileUri);
                                const editor = await vscode.window.showTextDocument(doc, {
                                    viewColumn: vscode.ViewColumn.One,
                                    preserveFocus: false
                                });
                                const line = Math.max(0, message.line - 1);
                                const pos = new vscode.Position(line, 0);
                                editor.selection = new vscode.Selection(pos, pos);
                                editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
                            } catch (err: any) {
                                vscode.window.showErrorMessage(`Senpy: Could not open file: ${err.message}`);
                            }
                        } else if (message.command === 'nodeNotFound') {
                            vscode.window.showInformationMessage(`Senpy: No source coordinates found for '${message.nodeName}'.`);
                        }
                    });

                    panel.webview.html = getWebviewContent(graphText, metaJson);
                    resolve();
                });
            });
        });
    });

    context.subscriptions.push(graphCmd);
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}

function getWebviewContent(graphContent: string, metaJson: string): string {
    const safeSource = graphContent
        .replace(/\\/g, '\\\\')
        .replace(/`/g, '\\`')
        .replace(/\$/g, '\\$');

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: data:; script-src https: 'unsafe-inline'; style-src https: 'unsafe-inline';">
    <title>Story Graph</title>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
    <style>
        body, html { 
            margin: 0; 
            padding: 0; 
            width: 100%; 
            height: 100%; 
            overflow: hidden; 
            background-color: var(--vscode-editor-background); 
            color: var(--vscode-editor-foreground); 
            font-family: var(--vscode-font-family);
        }
        #topbar {
            position: absolute;
            top: 10px;
            right: 15px;
            z-index: 100;
            display: flex;
            gap: 6px;
        }
        button {
            background-color: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: 1px solid var(--vscode-button-border, transparent);
            padding: 6px 12px;
            cursor: pointer;
            border-radius: 3px;
            font-size: 12px;
        }
        button:hover {
            background-color: var(--vscode-button-hoverBackground);
        }
        #graph-container { 
            width: 100%; 
            height: 100%; 
            display: flex; 
            justify-content: center; 
            align-items: center; 
        }
        #render-target { 
            width: 100%; 
            height: 100%; 
        }
        svg { 
            width: 100% !important; 
            height: 100% !important; 
        }

        /* Интерактивность узлов */
        .node {
            cursor: pointer !important;
            transition: transform 0.1s ease, filter 0.15s ease;
        }
        .node:hover {
            filter: drop-shadow(0 0 8px #007acc) brightness(1.25) !important;
        }
        .node:active {
            filter: brightness(0.9) !important;
        }
    </style>
</head>
<body>
    <div id="topbar">
        <button onclick="window.panZoom && window.panZoom.zoomIn()">Zoom In (+)</button>
        <button onclick="window.panZoom && window.panZoom.zoomOut()">Zoom Out (-)</button>
        <button onclick="window.panZoom && (window.panZoom.resetZoom(), window.panZoom.center())">Reset</button>
    </div>

    <div id="graph-container">
        <div id="render-target">
            <div style="padding: 20px; color: var(--vscode-descriptionForeground);">Rendering story graph...</div>
        </div>
    </div>

    <!-- Встраиваем метаданные в безопасный JSON контейнер -->
    <script id="senpy-metadata" type="application/json">
        ${metaJson}
    </script>
    
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        
        const vscode = acquireVsCodeApi();
        const metaElement = document.getElementById('senpy-metadata');
        let meta = { locations: {} };
        try {
            meta = JSON.parse(metaElement.textContent || '{}');
        } catch(e) {}

        const isLight = document.body.classList.contains('vscode-light');
        mermaid.initialize({ 
            startOnLoad: false, 
            theme: isLight ? 'default' : 'dark',
            maxTextSize: 1000000,
            securityLevel: 'loose'
        });

        const graphDefinition = \`${safeSource}\`;

        async function render() {
            const target = document.getElementById('render-target');
            try {
                const { svg } = await mermaid.render('mermaid-svg', graphDefinition);
                target.innerHTML = svg;

                const svgElement = target.querySelector('svg');
                svgElement.setAttribute('width', '100%');
                svgElement.setAttribute('height', '100%');
                
                // Навешиваем кликабельность на все узлы графа
                target.addEventListener('click', (e) => {
                    const nodeElem = e.target.closest('.node');
                    if (!nodeElem) return;
                    
                    const labelSpan = nodeElem.querySelector('.nodeLabel');
                    const nodeName = labelSpan ? labelSpan.textContent.trim() : null;
                    if (!nodeName) return;

                    const loc = meta.locations && meta.locations[nodeName];
                    if (loc) {
                        vscode.postMessage({
                            command: 'openLocation',
                            file: loc.file,
                            line: loc.line,
                            nodeName: nodeName,
                            type: loc.type
                        });
                    } else {
                        vscode.postMessage({
                            command: 'nodeNotFound',
                            nodeName: nodeName
                        });
                    }
                });

                window.panZoom = svgPanZoom(svgElement, {
                    zoomEnabled: true,
                    controlIconsEnabled: false,
                    fit: true,
                    center: true,
                    minZoom: 0.05,
                    maxZoom: 50
                });
            } catch (e) {
                target.innerHTML = '<div style="padding: 20px; color: var(--vscode-errorForeground);"><b>Failed to render graph:</b><br><br><pre>' + e + '</pre></div>';
            }
        }
        render();
    </script>
</body>
</html>`;
}