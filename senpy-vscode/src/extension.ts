import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';
import * as cp from 'child_process';

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
    const config = vscode.workspace.getConfiguration("senpy");
    let serverCmd = config.get<string>("executablePath") || "senpy";

    // Инициализация LSP Сервера
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

    // Новая команда: Генерация и показ интерактивного графа
    let graphCmd = vscode.commands.registerCommand('senpy.showStoryGraph', async () => {
        if (!vscode.workspace.workspaceFolders) {
            vscode.window.showErrorMessage("Please open a Ren'Py project folder first.");
            return;
        }

        const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Senpy: Generating Story Graph...",
            cancellable: false
        }, async () => {
            return new Promise<void>((resolve, reject) => {
                // Вызываем senpy --graph с увеличенным буфером (до 10 МБ), так как графы бывают огромными
                cp.exec(`"${serverCmd}" --graph`, { cwd: workspaceRoot, maxBuffer: 1024 * 1024 * 10 }, (error, stdout, stderr) => {
                    if (error) {
                        vscode.window.showErrorMessage(`Failed to generate graph: ${stderr || error.message}`);
                        reject();
                        return;
                    }

                    // Вырезаем Markdown-оформление (```mermaid ... ```), чтобы отдать чистый код библиотеке
                    let graphText = stdout.replace(/```mermaid\s*/g, '').replace(/```\s*$/g, '');

                    // Создаём Webview панель
                    const panel = vscode.window.createWebviewPanel(
                        'senpyGraph',
                        'Story Flow Graph',
                        vscode.ViewColumn.Beside, // Открываем в соседней вкладке
                        { enableScripts: true, retainContextWhenHidden: true }
                    );

                    panel.webview.html = getWebviewContent(graphText);
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

// HTML-шаблон для Webview с Mermaid и SVG-Pan-Zoom
function getWebviewContent(graphContent: string): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Story Graph</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background-color: var(--vscode-editor-background); color: var(--vscode-editor-foreground); }
        #graph-container { width: 100%; height: 100vh; display: flex; justify-content: center; align-items: center; }
        svg { width: 100% !important; height: 100% !important; }
    </style>
</head>
<body>
    <div id="graph-container">
        <!-- Скрытый блок с кодом -->
        <pre id="mermaid-source" style="display:none;">${graphContent}</pre>
        <!-- Блок для рендера -->
        <div id="render-target" style="width: 100%; height: 100%;"></div>
    </div>
    
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        
        // Настраиваем Mermaid под тему редактора
        const isLight = document.body.classList.contains('vscode-light');
        mermaid.initialize({ 
            startOnLoad: false, 
            theme: isLight ? 'default' : 'dark',
            maxTextSize: 1000000 // Для гигантских модов
        });

        async function render() {
            const source = document.getElementById('mermaid-source').textContent;
            const target = document.getElementById('render-target');
            
            try {
                const { svg } = await mermaid.render('generated-svg', source);
                target.innerHTML = svg;

                // Загружаем svg-pan-zoom для скролла мышкой
                const script = document.createElement('script');
                script.src = 'https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js';
                script.onload = () => {
                    const svgElement = target.querySelector('svg');
                    svgElement.setAttribute('width', '100%');
                    svgElement.setAttribute('height', '100%');
                    svgPanZoom(svgElement, {
                        zoomEnabled: true,
                        controlIconsEnabled: true, // Включаем UI-кнопки
                        fit: true,
                        center: true,
                        minZoom: 0.1,
                        maxZoom: 50
                    });
                };
                document.head.appendChild(script);
            } catch (e) {
                target.innerHTML = '<div style="padding: 20px; color: red;">Failed to render graph. The story might be too complex or contain syntax errors.<br><br>' + e + '</div>';
            }
        }
        render();
    </script>
</body>
</html>`;
}