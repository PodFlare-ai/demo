"""Minimal Podflare example — create a sandbox, run code, close it.

Setup:
    pip install podflare
    export PODFLARE_API_KEY=pf_live_...    # mint at dashboard.podflare.ai/keys

Run:
    python hello.py

What you'll see: ~250 ms total (residential wifi) or ~50 ms (in-cloud).
The `with` block ensures the sandbox is destroyed even if your code errors.
"""
from podflare import Sandbox


def main() -> None:
    with Sandbox() as sb:
        # Python REPL — variables persist across run_code calls.
        sb.run_code("import math; x = math.sqrt(12345)")
        out = sb.run_code("print(f'sqrt(12345) = {x:.4f}')")
        print(out.stdout)

        # Bash works too. Same sandbox; same filesystem.
        sb.run_code("echo 'hello from $(uname -a)'", language="bash")

        # Real outbound network — pip, git, curl all work by default.
        sb.run_code(
            "import urllib.request; "
            "print(urllib.request.urlopen('https://cloudflare.com/cdn-cgi/trace')"
            ".read().decode().split()[0])"
        )


if __name__ == "__main__":
    main()
