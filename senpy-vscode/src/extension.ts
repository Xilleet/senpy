import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
    const config = vscode.workspace.getConfiguration("senpy");
    let serverCmd = resolveServerCommand(context);

    // 1. Инициализация LSP Сервера
    const serverOptions: ServerOptions = {
        run: { command: serverCmd, args: ["--lsp"] },
        debug: { command: serverCmd, args: ["--lsp"] }
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: "file", language: "renpy" }],
        // UX-EXT-4: synchronize - watch .senpy.toml so the LSP server
        // picks up config changes without VS Code window reload.
        synchronize: {
            // configurationSection removed (UX-EXT-7): was causing
            // "Ignoring notification for unknown method workspace/didChangeConfiguration"
            // in server logs. pygls does not auto-register this handler.
            // fileEvents below is sufficient - it triggers
            // workspace/didChangeWatchedFiles which the server handles.
            // fileEvents: on .senpy.toml change, fire workspace/didChangeWatchedFiles
            // so the server recomputes severity_overrides without restart.
            fileEvents: vscode.workspace.createFileSystemWatcher("**/.senpy.toml")
        }
    };

    client = new LanguageClient(
        "senpyLsp",
        "Senpy Language Server",
        serverOptions,
        clientOptions
    );

    client.start();

    // 2. Фоновая проверка обновлений .vsix с GitHub Releases
    checkForUpdates(context);

    // 3. Инспектор краш-логов: перехват traceback.txt во время игры (Пункт 8.6)
    setupCrashWatcher(context);

    // 4. Команда: Генерация и показ интерактивного графа
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
                // cp.execFile with array args — no shell interpolation.
                // Previously used cp.exec with template-string interpolation,
                // which exposed a shell-injection risk if workspaceRoot or
                // serverCmd contained shell metacharacters.
                cp.execFile(serverCmd, [workspaceRoot, '--graph'], { cwd: workspaceRoot, maxBuffer: 1024 * 1024 * 15, timeout: 60000, windowsHide: true }, (error, stdout, stderr) => {
                    if (error) {
                        vscode.window.showErrorMessage(`Senpy Graph Error: ${stderr || error.message}`);
                        reject();
                        return;
                    }

                    const mermaidMatch = stdout.match(/```mermaid\s*([\s\S]*?)\s*```/);
                    let graphText = mermaidMatch ? mermaidMatch[1].trim() : stdout.trim();

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
// 5. Команда: Сценарная аналитика и дашборд персонажей
    let statsCmd = vscode.commands.registerCommand('senpy.showStoryStats', async () => {
        if (!vscode.workspace.workspaceFolders || vscode.workspace.workspaceFolders.length === 0) {
            vscode.window.showErrorMessage("Senpy: Please open a Ren'Py project folder first.");
            return;
        }

        const workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Senpy: Calculating Story Analytics...",
            cancellable: false
        }, async () => {
            return new Promise<void>((resolve, reject) => {
                // SEC-6: cp.execFile with array args — no shell interpolation.
                cp.execFile(serverCmd, [workspaceRoot, '--stats', '--format', 'json'], { cwd: workspaceRoot, maxBuffer: 1024 * 1024 * 10, timeout: 60000, windowsHide: true }, (error, stdout, stderr) => {
                    if (error) {
                        vscode.window.showErrorMessage(`Senpy Stats Error: ${stderr || error.message}`);
                        reject();
                        return;
                    }

                    try {
                        const statsData = JSON.parse(stdout);
                        const panel = vscode.window.createWebviewPanel(
                            'senpyStats',
                            'Story & Character Analytics',
                            vscode.ViewColumn.Beside,
                            { enableScripts: true, retainContextWhenHidden: true }
                        );

                        panel.webview.html = getStatsWebviewContent(statsData);
                        resolve();
                    } catch (err: any) {
                        vscode.window.showErrorMessage(`Senpy: Failed to parse stats JSON: ${err.message}`);
                        reject();
                    }
                });
            });
        });
    });

    context.subscriptions.push(statsCmd);
    context.subscriptions.push(graphCmd);

    // 5. Команда: Restart Language Server (Ctrl+Shift+P → "Senpy: Restart Language Server")
    let restartCmd = vscode.commands.registerCommand('senpy.restartLanguageServer', async () => {
        if (!client) {
            vscode.window.showWarningMessage("Senpy Language Server is not running.");
            return;
        }
        await client.stop();
        // Clear cached state
        client.outputChannel.clear();
        client.start();
        vscode.window.showInformationMessage("Senpy Language Server restarted.");
    });
    context.subscriptions.push(restartCmd);
    
// Пробрасываем папку bin/ расширения в PATH встроенного терминала VS Code
    const binDir = path.join(context.extensionPath, 'bin');
    if (fs.existsSync(binDir)) {
        context.environmentVariableCollection.prepend('PATH', `${binDir}${path.delimiter}`);
    }
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}

/**
 * Перехватчик создания/обновления traceback.txt и errors.txt прямо во время плейтеста новеллы
 */
function setupCrashWatcher(context: vscode.ExtensionContext) {
    const watcher = vscode.workspace.createFileSystemWatcher('**/{traceback,errors}.txt');
    let lastHandledTime = 0;

    const handleCrash = async (uri: vscode.Uri) => {
        const now = Date.now();
        if (now - lastHandledTime < 2500) {
            return; // Защита от дублей уведомлений (2.5 сек)
        }
        lastHandledTime = now;

        try {
            const fileData = await vscode.workspace.fs.readFile(uri);
            const content = Buffer.from(fileData).toString('utf-8');

            // 1. Извлекаем место сбоя и тип исключения (ловит и стандартные, и кастомные классы исключений)
            const locMatch = content.match(/File\s+["']([^"']+\.rpy)["'],\s+line\s+(\d+)/);
            const excMatch = content.match(/^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|[A-Z][a-zA-Z0-9]+)):\s*([^\r\n]+)/m) ||
                             content.match(/([A-Za-z0-9_]*(?:Error|Exception)):\s*([^\r\n]+)/);

            if (!locMatch) {
                return;
            }

            const rpyRelPath = locMatch[1];
            const lineNum = parseInt(locMatch[2], 10);
            const excType = excMatch ? excMatch[1] : 'Runtime Error';
            const excMsg = excMatch ? excMatch[2].trim() : '';

            const isRu = vscode.env.language.startsWith('ru');
            const fileName = rpyRelPath.split(/[\\/]/).pop() || rpyRelPath;

            const jumpBtn = isRu ? `Перейти к ${fileName}:${lineNum}` : `Go to ${fileName}:${lineNum}`;
            const reportBtn = isRu ? "Сообщить об ошибке на GitHub" : "Report Issue on GitHub";
            const message = isRu
                ? `Обнаружен сбой игры (${excType})!`
                : `Ren'Py runtime crash detected (${excType})!`;

            const action = await vscode.window.showErrorMessage(
                `${message} ${excMsg ? `— ${excMsg}` : ''}`,
                jumpBtn,
                reportBtn
            );

            if (action === jumpBtn) {
                // 1. Проверяем, не является ли путь абсолютным и существующим на диске
                let targetUri: vscode.Uri | undefined;
                try {
                    const absCandidate = vscode.Uri.file(rpyRelPath);
                    await vscode.workspace.fs.stat(absCandidate);
                    targetUri = absCandidate;
                } catch {
                    // Путь относительный или не существует по абсолютному адресу
                }

                // Нормализуем путь: унифицируем слэши и срезаем ведущие /
                const normRel = rpyRelPath.replace(/\\/g, '/').replace(/^\/+/, '');
                const normRelClean = normRel.replace(/^game\//i, '');
                const fileNameOnly = normRel.split('/').pop() || normRel;

                // 2. Прямой поиск в папках рабочей области с учётом вариаций (game/ и без)
                if (!targetUri && vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
                    for (const folder of vscode.workspace.workspaceFolders) {
                        const candidates = [
                            vscode.Uri.joinPath(folder.uri, normRel),
                            vscode.Uri.joinPath(folder.uri, 'game', normRelClean),
                            vscode.Uri.joinPath(folder.uri, normRelClean)
                        ];

                        for (const candidate of candidates) {
                            try {
                                await vscode.workspace.fs.stat(candidate);
                                targetUri = candidate;
                                break;
                            } catch {
                                // Файл не найден по этому варианту пути
                            }
                        }
                        if (targetUri) {
                            break;
                        }
                    }
                }

                // 3. Фолбэк через findFiles с сопоставлением по максимальному совпадению сегментов пути
                if (!targetUri) {
                    const files = await vscode.workspace.findFiles(`**/${fileNameOnly}`);

                    if (files.length === 1) {
                        targetUri = files[0];
                    } else if (files.length > 1) {
                        // Если найдено несколько файлов с одинаковым именем (например, route_a/script.rpy и route_b/script.rpy)
                        // Выбираем тот, у которого совпадает максимальное количество сегментов пути с конца
                        const targetSegments = normRel.toLowerCase().split('/').filter(Boolean);
                        let bestMatch: vscode.Uri | undefined;
                        let maxMatchingSegments = -1;

                        for (const file of files) {
                            const relPath = vscode.workspace.asRelativePath(file, false).replace(/\\/g, '/').toLowerCase();
                            const fileSegments = relPath.split('/').filter(Boolean);

                            let matchingCount = 0;
                            const minLen = Math.min(targetSegments.length, fileSegments.length);
                            for (let i = 1; i <= minLen; i++) {
                                if (targetSegments[targetSegments.length - i] === fileSegments[fileSegments.length - i]) {
                                    matchingCount++;
                                } else {
                                    break;
                                }
                            }

                            if (matchingCount > maxMatchingSegments) {
                                maxMatchingSegments = matchingCount;
                                bestMatch = file;
                            }
                        }

                        targetUri = bestMatch || files[0];
                    }
                }

                if (targetUri) {
                    const doc = await vscode.workspace.openTextDocument(targetUri);
                    const editor = await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.One });
                    const pos = new vscode.Position(Math.max(0, lineNum - 1), 0);
                    editor.selection = new vscode.Selection(pos, pos);
                    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
                }
            } else if (action === reportBtn) {
                // 4. Формирование лога: сохраняем шапку с версией и хвост с реальным падением
                let tracebackSnippet = content.trim();
                if (tracebackSnippet.length > 2000) {
                    const header = tracebackSnippet.split(/\r?\n/).slice(0, 4).join('\n');
                    const tail = tracebackSnippet.slice(-1600);
                    tracebackSnippet = `${header}\n\n[... truncated ...]\n\n${tail}`;
                }

                const title = encodeURIComponent(`[Runtime Crash] ${excType}: ${excMsg}`);
                const body = encodeURIComponent(
                    `### Runtime Crash Report\n\n` +
                    `- **Exception:** \`${excType}: ${excMsg}\`\n` +
                    `- **Location:** \`${fileName}:${lineNum}\`\n\n` +
                    `### Traceback Snippet\n\`\`\`text\n${tracebackSnippet}\n\`\`\``
                );
                vscode.env.openExternal(vscode.Uri.parse(`https://github.com/Xilleet/senpy/issues/new?title=${title}&body=${body}`));
            }
        } catch {
            // Игнорируем ошибки чтения файла
        }
    };

    watcher.onDidCreate(handleCrash);
    watcher.onDidChange(handleCrash);
    context.subscriptions.push(watcher);
}

/**
 * Фоновая проверка наличия свежего релиза .vsix на GitHub
 */
async function checkForUpdates(context: vscode.ExtensionContext) {
    const GITHUB_REPO = "Xilleet/senpy";
    const currentVersion: string = context.extension.packageJSON.version || "0.0.0";

    const LAST_CHECK_KEY = "senpy_last_update_check";
    const lastCheck = context.globalState.get<number>(LAST_CHECK_KEY, 0);
    const now = Date.now();
    const SIX_HOURS = 6 * 60 * 60 * 1000;

    if (now - lastCheck < SIX_HOURS) {
        return;
    }
    await context.globalState.update(LAST_CHECK_KEY, now);

    try {
        const response = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/releases/latest`, {
            headers: { "User-Agent": "senpy-vscode-updater" }
        });

        if (!response.ok) {
            return;
        }

        const release = await response.json() as { 
            tag_name: string; 
            html_url: string; 
            assets: Array<{ name: string; browser_download_url: string }> 
        };

        const vsixAsset = release.assets?.find(a => a.name.endsWith(".vsix"));
        const downloadUrl = vsixAsset ? vsixAsset.browser_download_url : release.html_url;

        const fileVersionMatch = vsixAsset?.name.match(/(\d+\.\d+\.\d+)/);
        const latestVersion = fileVersionMatch ? fileVersionMatch[1] : release.tag_name.replace(/^v/, "").trim();

        if (isNewer(latestVersion, currentVersion)) {
            const action = await vscode.window.showInformationMessage(
                `Вышла новая версия Senpy v${latestVersion}! (у вас установлена v${currentVersion})`,
                "Скачать .vsix",
                "Что нового"
            );

            if (action === "Скачать .vsix") {
                vscode.env.openExternal(vscode.Uri.parse(downloadUrl));
            } else if (action === "Что нового") {
                vscode.env.openExternal(vscode.Uri.parse(release.html_url));
            }
        }
    } catch {
        // Игнорируем отсутствие сети
    }
}

function resolveServerCommand(context: vscode.ExtensionContext): string {
    const config = vscode.workspace.getConfiguration("senpy");
    const customPath = config.get<string>("executablePath");
    
    // 1. Приоритет: явный путь из настроек пользователя
    if (customPath && customPath.trim().length > 0) {
        return customPath.trim();
    }

    // 2. Приоритет: вшитый бинарник внутри папки расширения
    const isWin = process.platform === 'win32';
    const binName = isWin ? 'senpy.exe' : 'senpy';
    const bundledBinary = path.join(context.extensionPath, 'bin', binName);

    if (fs.existsSync(bundledBinary)) {
        return bundledBinary;
    }

    // 3. Fallback: глобальная команда в системе (pip install senpy-linter)
    return "senpy";
}

function isNewer(latest: string, current: string): boolean {
    const l = latest.split('.').map(x => parseInt(x, 10) || 0);
    const c = current.split('.').map(x => parseInt(x, 10) || 0);
    const maxLen = Math.max(l.length, c.length);

    for (let i = 0; i < maxLen; i++) {
        const lPart = l[i] ?? 0;
        const cPart = c[i] ?? 0;
        if (lPart > cPart) {
            return true;
        }
        if (lPart < cPart) {
            return false;
        }
    }
    return false;
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

function getStatsWebviewContent(data: any): string {
    const charsRows = (data.characters || []).map((c: any) => `
        <tr>
            <td style="font-weight: bold; color: var(--vscode-charts-blue);">${c.display_name}</td>
            <td style="color: var(--vscode-descriptionForeground); font-family: monospace;">${c.tag}</td>
            <td style="text-align: right;">${c.lines.toLocaleString()}</td>
            <td style="text-align: right; font-weight: bold; color: var(--vscode-charts-green);">${c.words.toLocaleString()}</td>
            <td style="text-align: right;">${c.percentage}%</td>
            <td style="width: 180px;">
                <div style="background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; height: 14px;">
                    <div style="width: ${c.percentage}%; background: var(--vscode-progressBar-background, #007acc); height: 100%;"></div>
                </div>
            </td>
        </tr>
    `).join('');

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Story Analytics</title>
    <style>
        body {
            font-family: var(--vscode-font-family);
            color: var(--vscode-editor-foreground);
            background-color: var(--vscode-editor-background);
            padding: 24px;
            margin: 0;
        }
        h2 { margin-top: 0; margin-bottom: 20px; font-weight: normal; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }
        .card {
            background-color: var(--vscode-editor-inactiveSelectionBackground, rgba(255,255,255,0.05));
            border: 1px solid var(--vscode-widget-border, #444);
            border-radius: 6px;
            padding: 16px;
        }
        .card-title {
            font-size: 12px;
            color: var(--vscode-descriptionForeground);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .card-value {
            font-size: 26px;
            font-weight: bold;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        th, td {
            padding: 10px 12px;
            text-align: left;
            border-bottom: 1px solid var(--vscode-widget-border, rgba(255,255,255,0.1));
            font-size: 13px;
        }
        th {
            color: var(--vscode-descriptionForeground);
            font-weight: 600;
        }
    </style>
</head>
<body>
    <h2>Story & Character Dialogue Analytics</h2>

    <div class="grid">
        <div class="card">
            <div class="card-title">Total Words</div>
            <div class="card-value" style="color: var(--vscode-charts-green);">${data.total_words.toLocaleString()}</div>
        </div>
        <div class="card">
            <div class="card-title">Dialogue Lines</div>
            <div class="card-value">${data.total_dialogue_lines.toLocaleString()}</div>
        </div>
        <div class="card">
            <div class="card-title">Estimated Reading Time</div>
            <div class="card-value" style="color: var(--vscode-charts-purple, #b180d7);">${data.reading_time_formatted}</div>
        </div>
        <div class="card">
            <div class="card-title">Cast Members</div>
            <div class="card-value" style="color: var(--vscode-charts-yellow, #dcdcaa);">${data.characters.length}</div>
        </div>
    </div>

    <h3 style="margin-bottom: 8px; font-weight: normal;">Cast Dialogue Distribution</h3>
    <table>
        <thead>
            <tr>
                <th>Character</th>
                <th>Tag</th>
                <th style="text-align: right;">Lines</th>
                <th style="text-align: right;">Words</th>
                <th style="text-align: right;">Share</th>
                <th>Visual Balance</th>
            </tr>
        </thead>
        <tbody>
            ${charsRows}
        </tbody>
    </table>
</body>
</html>`;
}