import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as cp from 'child_process';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions
} from 'vscode-languageclient/node';

let client: LanguageClient | undefined;
let outputChannel: vscode.LogOutputChannel;

interface ExecutableInfo {
    command: string;
    args: string[];
}

/**
 * Интеллектуальный поиск бинарника Senpy:
 * 1. Настройки пользователя (senpy.executablePath)
 * 2. Виртуальное окружение воркспейса (venv / .venv)
 * 3. Системный PATH
 * 4. python -m senpy
 */
function resolveSenpyExecutable(): ExecutableInfo | undefined {
    const config = vscode.workspace.getConfiguration('senpy');
    const customPath = config.get<string>('executablePath')?.trim();

    // 1. Проверяем кастомный путь из настроек
    if (customPath) {
        if (fs.existsSync(customPath)) {
            if (customPath.endsWith('.py')) {
                return { command: 'python', args: [customPath, '--lsp'] };
            }
            return { command: customPath, args: ['--lsp'] };
        } else {
            outputChannel.appendLine(`[Warn] Configured executablePath not found: ${customPath}`);
        }
    }

    // 2. Ищем локальный venv внутри открытых папок воркспейса
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (workspaceFolders) {
        for (const folder of workspaceFolders) {
            const root = folder.uri.fsPath;
            const candidates = [
                // Windows
                path.join(root, 'venv', 'Scripts', 'senpy.exe'),
                path.join(root, '.venv', 'Scripts', 'senpy.exe'),
                // Linux / macOS
                path.join(root, 'venv', 'bin', 'senpy'),
                path.join(root, '.venv', 'bin', 'senpy'),
            ];

            for (const candidate of candidates) {
                if (fs.existsSync(candidate)) {
                    outputChannel.appendLine(`[Info] Auto-detected Senpy in local venv: ${candidate}`);
                    return { command: candidate, args: ['--lsp'] };
                }
            }
        }
    }

    // 3. Проверяем наличие senpy в системном PATH
    try {
        const checkCmd = process.platform === 'win32' ? 'where senpy' : 'which senpy';
        const stdout = cp.execSync(checkCmd, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
        const firstLine = stdout.split(/\r?\n/)[0];
        if (firstLine && fs.existsSync(firstLine)) {
            outputChannel.appendLine(`[Info] Found Senpy in system PATH: ${firstLine}`);
            return { command: firstLine, args: ['--lsp'] };
        }
    } catch {
        // Не найден в PATH
    }

    // 4. Пробуем запустить через системный модуль python -m senpy
    try {
        cp.execSync('python -m senpy --help', { stdio: 'ignore' });
        outputChannel.appendLine('[Info] Falling back to: python -m senpy --lsp');
        return { command: 'python', args: ['-m', 'senpy', '--lsp'] };
    } catch {
        // Python модуль недоступен
    }

    return undefined;
}

async function startLanguageServer(context: vscode.ExtensionContext) {
    const execInfo = resolveSenpyExecutable();

    if (!execInfo) {
        outputChannel.appendLine('[Error] Senpy executable could not be resolved.');
        const choice = await vscode.window.showErrorMessage(
            "Notice me! Ядро Senpy не найдено. Установите его в venv (pip install -e .) или укажите путь в настройках.",
            "Specify Path",
            "Open Documentation"
        );

        if (choice === "Specify Path") {
            vscode.commands.executeCommand('workbench.action.openSettings', 'senpy.executablePath');
        } else if (choice === "Open Documentation") {
            vscode.env.openExternal(vscode.Uri.parse("https://github.com/Xilleet/senpy"));
        }
        return;
    }

    outputChannel.appendLine(`[Info] Starting Language Server: ${execInfo.command} ${execInfo.args.join(' ')}`);

    const serverOptions: ServerOptions = {
        command: execInfo.command,
        args: execInfo.args,
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'renpy' },
            { scheme: 'untitled', language: 'renpy' }
        ],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.rpy')
        },
        outputChannel: outputChannel,
        traceOutputChannel: outputChannel,
    };

    client = new LanguageClient(
        'senpyServer',
        'Senpy Language Server',
        serverOptions,
        clientOptions
    );

    try {
        await client.start();
        outputChannel.appendLine('[Success] Senpy Language Server successfully started!');
    } catch (err) {
        outputChannel.appendLine(`[Error] Failed to start Language Server: ${err}`);
        vscode.window.showErrorMessage(`Senpy LSP failed to start: ${err}`);
    }
}

export async function activate(context: vscode.ExtensionContext) {
    // Создаем именно LogOutputChannel через { log: true }
    outputChannel = vscode.window.createOutputChannel('Senpy Language Server', { log: true });
    context.subscriptions.push(outputChannel);

    // Команда для ручного перезапуска сервера
    context.subscriptions.push(
        vscode.commands.registerCommand('senpy.restartServer', async () => {
            outputChannel.appendLine('[Info] Restarting Senpy server...');
            if (client) {
                await client.stop();
                client = undefined;
            }
            await startLanguageServer(context);
            vscode.window.showInformationMessage('Senpy Language Server restarted.');
        })
    );

    await startLanguageServer(context);
}

export async function deactivate(): Promise<void> {
    if (client) {
        await client.stop();
        client = undefined;
    }
}