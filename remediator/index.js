import express from "express";
import Docker from "dockerode";

const app = express();
app.use(express.json({ limit: "1mb" }));

const TOKEN = String(process.env.REMEDIATOR_TOKEN || "").trim();
if (!TOKEN) {
  console.error("Missing env var: REMEDIATOR_TOKEN");
  process.exit(1);
}

const TARGET_CONTAINER = String(process.env.TARGET_CONTAINER || "telegram-interface").trim();
const MIN_SECONDS = Number(process.env.MIN_SECONDS_BETWEEN_RESTARTS || 180);
const PORT = Number(process.env.PORT || 8090);

const docker = new Docker({ socketPath: "/var/run/docker.sock" });

let lastRestartAt = 0;

function authOk(req) {
  const got = req.header("x-remediator-token") || "";
  return got === TOKEN;
}

async function restartContainerByName(name) {
  const containers = await docker.listContainers({ all: true });
  const match = containers.find(c => (c.Names || []).some(n => n.replace(/^\//, "") === name));
  if (!match) throw new Error(`Container not found: ${name}`);

  const c = docker.getContainer(match.Id);

  try { await c.stop({ t: 10 }); } catch {}
  await c.start();

  return { id: match.Id, name };
}

app.get("/health", (req, res) => res.status(200).send("ok"));

app.post("/restart/telegram", async (req, res) => {
  if (!authOk(req)) return res.status(401).json({ ok: false, error: "unauthorized" });

  const now = Date.now();
  if (lastRestartAt && (now - lastRestartAt) < MIN_SECONDS * 1000) {
    return res.status(429).json({
      ok: false,
      error: "rate_limited",
      retry_after_seconds: Math.ceil((MIN_SECONDS * 1000 - (now - lastRestartAt)) / 1000)
    });
  }

  try {
    const out = await restartContainerByName(TARGET_CONTAINER);
    lastRestartAt = now;
    return res.json({ ok: true, restarted: out, at: new Date(now).toISOString() });
  } catch (e) {
    return res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

app.listen(PORT, "0.0.0.0", () => console.log(`Remediator listening on :${PORT}`));
