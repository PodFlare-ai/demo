/**
 * Minimal Podflare example — create a sandbox, run code, close it.
 *
 * Setup:
 *     npm install podflare
 *     export PODFLARE_API_KEY=pf_live_...   // mint at dashboard.podflare.ai/keys
 *
 * Run:
 *     npx tsx hello.ts
 */
import { Sandbox } from "podflare";

async function main(): Promise<void> {
  const sb = await Sandbox.create();
  try {
    // Python REPL — variables persist across runCode calls.
    await sb.runCode("import math; x = math.sqrt(12345)");
    const out = await sb.runCode("print(f'sqrt(12345) = {x:.4f}')");
    console.log(out.stdout);

    // Bash works too. Same sandbox, same filesystem.
    await sb.runCode("echo 'hello from $(uname -a)'", "bash");

    // Real outbound network — pip, git, curl all work by default.
    const trace = await sb.runCode(
      "import urllib.request; " +
      "print(urllib.request.urlopen('https://cloudflare.com/cdn-cgi/trace').read().decode().split()[0])",
    );
    console.log(trace.stdout.trim());
  } finally {
    await sb.close();
  }
}

main();
