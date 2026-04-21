/**
 * Code Interpreter REPL — ask anything, the AI writes code and runs it.
 *
 * The ChatGPT "Advanced Data Analysis" pattern in ~150 lines. Spin up a
 * Podflare sandbox, hand the model a `run_code` tool, let it solve
 * whatever you throw at it. Sandbox state PERSISTS across turns —
 * variables, imports, downloaded files, plots — so you build up state
 * across a conversation just like the web UIs.
 *
 * Try asking:
 *     > Plot a sine wave from 0 to 2π and save it as sine.png
 *     > Now save it base64-encoded to clipboard.txt
 *     > Download the latest BTC price from coingecko and tell me the trend
 *     > How many primes are there below 10,000?
 *
 * Setup:
 *     npm install podflare openai
 *     export PODFLARE_API_KEY=pf_live_...   // mint at dashboard.podflare.ai/keys
 *     export OPENAI_API_KEY=sk-...
 *
 * Run:
 *     npx tsx code-interpreter.ts
 */
import { createInterface } from "node:readline/promises";
import { stdin, stdout, stderr } from "node:process";
import OpenAI from "openai";
import { Sandbox } from "podflare";

const SYSTEM_PROMPT = `You are a code-interpreter assistant.

You have a \`run_code\` tool that executes Python (or bash) in a private
Linux sandbox with full internet access. Use it for anything that
benefits from real execution: math, data downloads, plotting, parsing,
testing hypotheses, calling APIs, etc.

The sandbox state PERSISTS across calls in this conversation — variables
you define, imports you make, and files you write all survive. Use that:
download data once, analyze it across many turns.

When you write code, prefer concise programs that print their result. The
user sees stdout. For plots, save to a PNG and tell the user the path.`;

const PODFLARE_TOOL = {
  type: "function" as const,
  function: {
    name: "run_code",
    description:
      "Execute code in an isolated Firecracker sandbox. The same " +
      "sandbox is reused across every call in this conversation, so " +
      "variables, imports, and files persist. Returns stdout, stderr, " +
      "exit_code.",
    parameters: {
      type: "object",
      properties: {
        code: { type: "string", description: "Code to execute." },
        language: {
          type: "string",
          enum: ["python", "bash"],
          description: "Runtime; defaults to python.",
        },
      },
      required: ["code"],
    },
  },
};

async function main(): Promise<void> {
  const client = new OpenAI();

  // SDK ≥ 0.0.16 picks the nearest region from your timezone — no Worker
  // hop on the first call. SDK ≥ 0.0.17 caps tail latency at p99 < 1 s.
  stdout.write("creating sandbox... ");
  const sandbox = await Sandbox.create();
  stdout.write("ready.\n");
  console.log("─".repeat(60));
  console.log("Type a question (or 'exit'):");

  const rl = createInterface({ input: stdin, output: stdout });
  // OpenAI's typed messages array — we mutate as the agent loop progresses.
  const messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
    { role: "system", content: SYSTEM_PROMPT },
  ];

  try {
    while (true) {
      let user: string;
      try {
        user = (await rl.question("\n> ")).trim();
      } catch {
        return; // EOF / Ctrl-C
      }
      if (["exit", "quit", ":q"].includes(user.toLowerCase())) return;
      if (!user) continue;

      messages.push({ role: "user", content: user });
      await agentLoop(client, sandbox, messages);
    }
  } finally {
    rl.close();
    await sandbox.close();
  }
}

async function agentLoop(
  client: OpenAI,
  sandbox: Sandbox,
  messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[],
): Promise<void> {
  for (let step = 0; step < 10; step++) {
    const resp = await client.chat.completions.create({
      model: "gpt-5.1",
      messages,
      tools: [PODFLARE_TOOL],
    });
    const msg = resp.choices[0]!.message;
    messages.push(msg);

    if (!msg.tool_calls?.length) {
      // Model has its final answer.
      console.log(`\n${msg.content}`);
      return;
    }

    for (const call of msg.tool_calls) {
      if (call.type !== "function") continue;
      const args = JSON.parse(call.function.arguments) as {
        code: string;
        language?: "python" | "bash";
      };
      const language = args.language ?? "python";
      // Show the user what the model is about to run — transparency is
      // half the point of running it ourselves vs a black-box vendor's
      // "advanced data analysis."
      console.log(`\n  ┌─ run_code (${language}) ─${"─".repeat(40)}`);
      for (const line of args.code.split("\n")) console.log(`  │ ${line}`);
      const r = await sandbox.runCode(args.code, language);
      console.log(`  └─ exit=${r.exitCode}${"─".repeat(40)}`);
      if (r.stdout.trim()) {
        for (const line of r.stdout.trimEnd().split("\n")) {
          console.log(`    ${line}`);
        }
      }
      if (r.stderr.trim()) {
        for (const line of r.stderr.trimEnd().split("\n")) {
          stderr.write(`    [stderr] ${line}\n`);
        }
      }

      messages.push({
        role: "tool",
        tool_call_id: call.id,
        content:
          `stdout:\n${r.stdout}\n` +
          `stderr:\n${r.stderr}\n` +
          `exit_code: ${r.exitCode}`,
      });
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
