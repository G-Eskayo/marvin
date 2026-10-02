/*
 * Frida instrumentation script: hook a function and log args/return/backtrace.
 *
 * Edit TARGET_FUNCTION below to trace a different exported function.
 *
 * Usage with frida_attach.py:
 *     python3 frida_attach.py --spawn ./myapp --script frida_trace_example.js --i-own-this-target
 */

const TARGET_FUNCTION = 'main';  // Change this to trace a different function

console.log('[*] Frida instrumentation starting...');
console.log('[*] Target function: ' + TARGET_FUNCTION);

const targetFunc = Module.findExportByName(null, TARGET_FUNCTION);

if (!targetFunc) {
    console.log('[!] Function "' + TARGET_FUNCTION + '" not found.');
    console.log('[*] Available exports:');

    // List available exports (first 10)
    const modules = Process.enumerateModules();
    let count = 0;
    for (let i = 0; i < modules.length && count < 10; i++) {
        try {
            const exports = modules[i].enumerateExports();
            for (let j = 0; j < exports.length && count < 10; j++) {
                console.log('    ' + exports[j].name);
                count++;
            }
        } catch (e) {
            // Skip modules that can't be enumerated
        }
    }
} else {
    console.log('[+] Hooked "' + TARGET_FUNCTION + '" at ' + targetFunc);

    Interceptor.attach(targetFunc, {
        onEnter(args) {
            console.log('\n[CALL] ' + TARGET_FUNCTION + '(');

            // Log arguments (up to 8, or customize based on function signature)
            for (let i = 0; i < Math.min(args.length, 8); i++) {
                const arg = args[i];
                let argStr = '';

                // Try to print as different types
                try {
                    // Check if it looks like a string pointer
                    if (arg.isNull()) {
                        argStr = 'NULL';
                    } else if (arg.toInt32) {
                        argStr = '0x' + arg.toString(16);
                    } else {
                        argStr = arg.toString();
                    }
                } catch (e) {
                    argStr = arg.toString();
                }

                console.log('  arg' + i + ': ' + argStr);
            }

            console.log(');');

            // Log backtrace
            console.log('[BACKTRACE]');
            try {
                const bt = Thread.backtrace(this.context, Backtracer.ACCURATE);
                for (let i = 0; i < Math.min(bt.length, 10); i++) {
                    const sym = DebugSymbol.fromAddress(bt[i]);
                    console.log('  [' + i + '] ' + sym);
                }
            } catch (e) {
                console.log('  (backtrace unavailable: ' + e.message + ')');
            }
        },

        onLeave(retval) {
            let retStr = '';
            try {
                if (retval.isNull()) {
                    retStr = 'NULL';
                } else if (retval.toInt32) {
                    retStr = '0x' + retval.toString(16);
                } else {
                    retStr = retval.toString();
                }
            } catch (e) {
                retStr = retval.toString();
            }

            console.log('[RETURN] ' + TARGET_FUNCTION + ' -> ' + retStr + '\n');
        }
    });
}

console.log('[+] Instrumentation active. Output will be printed as the function is called.');
