#!/usr/bin/env node
import { parseCli, runHeadless, UsageError, USAGE } from '../src/cli.js';

// `app-telemetry sql ... | head`: the reader leaving early is not an error.
process.stdout.on('error', error => {
    if (error.code !== 'EPIPE')
        throw error;
    process.exit(0);
});

try {
    const { options, command, args } = parseCli(process.argv.slice(2));
    if (options.help) {
        process.stdout.write(USAGE);
    }
    else if (command !== undefined || options.headless || !process.stdout.isTTY || !process.stdin.isTTY) {
        await runHeadless(command, args, options);
    }
    else {
        const { runTui } = await import('../src/tui.js');
        await runTui(options);
        // Quit means quit: a listing still in flight would keep node alive.
        process.exit(0);
    }
}
catch (error) {
    process.stderr.write(`app-telemetry: ${error.message}\n`);
    if (error instanceof UsageError)
        process.stderr.write(USAGE);
    process.exitCode = error instanceof UsageError ? 2 : 1;
}