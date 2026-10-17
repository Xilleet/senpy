import * as vscode from 'vscode';
import * as cp from 'child_process';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions
} from 'vscode-languageclient/node';

let client: LanguageClient | undefined;

/**
 * Проверяет, откликается ли команда/бинарник в системе.
 */
function checkCommandExists(command: string): Promise<boolean> {
    return new Promise((resolve) => {
        // Пробуем запустить команду с ключом --help
        cp.exec(`"${command}" --help`, (error) => {
            // Если ошибки нет — бинарник доступен и работает
            resolve(!error);
        });
    });
}

export async function activate(context: vscode.ExtensionContext) {
    // 1. Получаем путь из настроек пользователя
    const config = vscode.workspace.getConfiguration('senpy');
    let executable = config.get<string>('executablePath')?.trim();

    // Если в настройках пусто — используем системную команду по умолчанию
    if (!executable) {
        executable = 'senpy';
    }

    // 2. Проверяем, существует ли и доступен ли senpy
    const isAvailable = await checkCommandExists(executable);

    if (!isAvailable) {
        // Показываем красивое модальное/всплывающее уведомление с кнопками действий
        const choice = await vscode.window.showErrorMessage(
            "Notice me! Ядро Senpy не найдено в PATH. Установи его через pip или укажи путь в настройках.",
            "Install via pip",
            "Specify Path",
            "Open Documentation"
        );

        if (choice === "Install via pip") {
            // Создаем терминал прямо в VS Code и запускаем pip install
            const terminal = vscode.window.createTerminal("Senpy Installer");
            terminal.show();
            terminal.sendText("pip install -U senpy-linter");
        } else if (choice === "Specify Path") {
            // Открываем настройки VS Code точно на нашей опции
            vscode.commands.executeCommand('workbench.action.openSettings', 'senpy.executablePath');
        } else if (choice === "Open Documentation") {
            // Открываем браузер со ссылкой на твой GitHub
            vscode.env.openExternal(vscode.Uri.parse("https://github.com/Xilleet/senpy"));
        }

        // Прерываем активацию LSP, пока пользователь не поставит пакет
        return;
    }

    // 3. Если всё в порядке — настраиваем и стартуем LSP сервер
    const serverOptions: ServerOptions = {
        command: executable,
        args: ['--lsp']
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'renpy' }],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.rpy')
        }
    };

    client = new LanguageClient(
        'senpyServer',
        'Senpy Language Server',
        serverOptions,
        clientOptions
    );

    // Запускаем сервер
    await client.start();
}

export function deactivate(): Thenable<void> | undefined {
    if (!client) {
        return undefined;
    }
    return client.stop();
}