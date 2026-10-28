import * as assert from 'assert';
import * as vscode from 'vscode';

suite('Senpy Extension Test Suite', () => {
    vscode.window.showInformationMessage('Starting E2E tests.');

    test('Extension should be present and active', async () => {
        // Имя расширения берётся из publisher.name в package.json
        const extension = vscode.extensions.getExtension('Xilleet.senpy-vscode');
        assert.ok(extension, 'Extension is not installed or not found in the host workspace.');
        
        if (!extension.isActive) {
            await extension.activate();
        }
        assert.ok(extension.isActive, 'Extension failed to activate.');
    });

    test('Commands should be registered', async () => {
        const commands = await vscode.commands.getCommands(true);
        assert.ok(
            commands.includes('senpy.showStoryGraph'),
            'senpy.showStoryGraph command is missing from registry.'
        );
    });
});