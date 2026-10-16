import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { LanguageClient, LanguageClientOptions, ServerOptions } from 'vscode-languageclient/node';

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
    // 1. Ищем senpy: сначала проверяем venv в воркспейсе, если нет — берем системный 'senpy'
    let command = 'senpy';
    
    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
        const root = folders[0].uri.fsPath;
        const venvSenpyWin = path.join(root, 'venv', 'Scripts', 'senpy.exe');
        const dotVenvSenpyWin = path.join(root, '.venv', 'Scripts', 'senpy.exe');
        
        if (fs.existsSync(venvSenpyWin)) {
            command = venvSenpyWin;
        } else if (fs.existsSync(dotVenvSenpyWin)) {
            command = dotVenvSenpyWin;
        }
    }

    // 2. Настройки сервера
    const serverOptions: ServerOptions = {
        command: command,
        args: ['--lsp'],
    };

    // 3. Селектор файлов Ren'Py
    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'renpy' },
            { scheme: 'file', pattern: '**/*.rpy' }
        ],
    };

    client = new LanguageClient(
        'senpyLsp',
        'Senpy Language Server',
        serverOptions,
        clientOptions
    );

    client.start();
}

export function deactivate(): Thenable<void> | undefined {
    return client ? client.stop() : undefined;
}