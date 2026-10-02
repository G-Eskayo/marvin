#!/usr/bin/env python3
"""
Frida attachment launcher: spawn or attach to a process and load an instrumentation script.

Usage:
    python3 frida_attach.py --spawn <binary> --script <script.js> --i-own-this-target
    python3 frida_attach.py --pid <pid> --script <script.js> --i-own-this-target
    python3 frida_attach.py --process-name <name> --script <script.js> --i-own-this-target

Examples:
    # Spawn and trace
    python3 frida_attach.py --spawn ./myapp --script hook.js --i-own-this-target

    # Attach to running process
    python3 frida_attach.py --pid 1234 --script hook.js --i-own-this-target

    # Attach by name
    python3 frida_attach.py --process-name firefox --script hook.js --i-own-this-target
"""
import argparse
import sys
from pathlib import Path


def check_authorization(args: argparse.Namespace) -> bool:
    """Authorization gate — requires explicit --i-own-this-target flag."""
    if not getattr(args, 'i_own_this_target', False):
        print(
            "[!] Authorization gate: you must confirm --i-own-this-target "
            "before running instrumentation on a process.",
            file=sys.stderr
        )
        return False
    return True


def check_frida():
    """Check if Frida is installed."""
    try:
        import frida  # noqa: F401
        return True
    except ImportError:
        print(
            "[!] Frida not installed. Install with: pip install frida",
            file=sys.stderr
        )
        return False


def load_script(script_path: str) -> str:
    """Load the instrumentation script from disk."""
    script_file = Path(script_path).resolve()
    if not script_file.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    return script_file.read_text()


def main():
    parser = argparse.ArgumentParser(
        description="Frida process attachment and instrumentation launcher.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--spawn", help="Spawn a new process from binary path")
    target_group.add_argument("--pid", type=int, help="Attach to process by PID")
    target_group.add_argument("--process-name", help="Attach to process by name")

    parser.add_argument(
        "--script",
        required=True,
        help="Path to Frida instrumentation script (.js)"
    )
    parser.add_argument(
        "--i-own-this-target",
        action="store_true",
        required=True,
        help="Authorization gate: confirm you own or are authorized for this target"
    )

    args = parser.parse_args()

    if not check_authorization(args):
        sys.exit(1)

    if not check_frida():
        sys.exit(1)

    try:
        import frida

        # Load the instrumentation script
        script_source = load_script(args.script)

        # Attach to or spawn a process
        if args.spawn:
            # Spawn a new process
            spawn_path = Path(args.spawn).resolve()
            if not spawn_path.exists():
                raise FileNotFoundError(f"Binary not found: {args.spawn}")

            print(f"[*] Spawning process: {spawn_path}", file=sys.stderr)
            pid = frida.spawn([str(spawn_path)])
            session = frida.attach(pid)
            frida.resume(pid)

        elif args.pid:
            # Attach to existing process by PID
            print(f"[*] Attaching to PID {args.pid}", file=sys.stderr)
            session = frida.attach(args.pid)

        elif args.process_name:
            # Attach to process by name
            print(f"[*] Attaching to process: {args.process_name}", file=sys.stderr)
            device = frida.get_usb_device(timeout=1) if sys.platform == 'darwin' else frida.get_local_device()
            session = device.attach(args.process_name)

        # Load the script into the process
        print("[*] Loading instrumentation script...", file=sys.stderr)
        script = session.create_script(script_source)
        script.on('message', on_message)
        script.load()

        print("[+] Instrumentation loaded. Press Ctrl+C to exit.", file=sys.stderr)
        sys.stdin.read()

    except frida.ProcessNotFoundError as e:
        print(f"[!] Process not found: {e}", file=sys.stderr)
        sys.exit(1)
    except frida.TransportError as e:
        print(f"[!] Failed to attach: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if 'session' in locals():
            try:
                session.detach()
            except:
                pass


def on_message(message, data):
    """Handle messages from the Frida script."""
    if message['type'] == 'send':
        print(message['payload'], file=sys.stderr)
    elif message['type'] == 'error':
        print(f"[!] Script error: {message['stack']}", file=sys.stderr)


if __name__ == "__main__":
    main()
