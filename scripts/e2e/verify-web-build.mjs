import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const WEB_URL = (process.env.E2E_WEB_URL ?? "http://127.0.0.1:4173").replace(/\/+$/, "");
const OUTPUT_PATH = path.resolve(process.cwd(), "output", "playwright", "web-build-verification.json");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: {
      "cache-control": "no-cache",
      pragma: "no-cache",
    },
  });
  assert(response.ok, `GET ${url} failed with ${response.status}`);
  return {
    payload: await response.json(),
    cacheControl: response.headers.get("cache-control"),
  };
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: {
      "cache-control": "no-cache",
      pragma: "no-cache",
    },
  });
  assert(response.ok, `GET ${url} failed with ${response.status}`);
  return {
    text: await response.text(),
    cacheControl: response.headers.get("cache-control"),
  };
}

async function main() {
  await fs.mkdir(path.dirname(OUTPUT_PATH), { recursive: true });

  const containerBuildMeta = JSON.parse(
    execFileSync(
      "docker",
      ["compose", "-f", "infra/docker-compose.local.yml", "exec", "-T", "web", "cat", "/usr/share/nginx/html/build-meta.json"],
      { cwd: process.cwd(), encoding: "utf8" },
    ),
  );
  const servedBuildMetaResponse = await fetchJson(`${WEB_URL}/build-meta.json`);
  const servedIndexResponse = await fetchText(`${WEB_URL}/`);

  assert(
    servedBuildMetaResponse.payload.buildId === containerBuildMeta.buildId,
    `Served build id ${servedBuildMetaResponse.payload.buildId} did not match container build ${containerBuildMeta.buildId}`,
  );
  assert(
    servedBuildMetaResponse.payload.sourceHash === containerBuildMeta.sourceHash,
    `Served source hash ${servedBuildMetaResponse.payload.sourceHash} did not match container build ${containerBuildMeta.sourceHash}`,
  );
  assert(
    servedIndexResponse.text.includes(containerBuildMeta.buildId),
    "Served index.html did not expose the expected build id meta tag",
  );
  assert(
    (servedIndexResponse.cacheControl ?? "").includes("no-store"),
    `Expected index.html to be served with no-store, got '${servedIndexResponse.cacheControl ?? ""}'`,
  );
  assert(
    (servedBuildMetaResponse.cacheControl ?? "").includes("no-store"),
    `Expected build-meta.json to be served with no-store, got '${servedBuildMetaResponse.cacheControl ?? ""}'`,
  );

  await fs.writeFile(
    OUTPUT_PATH,
    JSON.stringify(
      {
        completedAt: new Date().toISOString(),
        webUrl: WEB_URL,
        status: "passed",
        buildId: containerBuildMeta.buildId,
        sourceHash: containerBuildMeta.sourceHash,
        indexCacheControl: servedIndexResponse.cacheControl,
        buildMetaCacheControl: servedBuildMetaResponse.cacheControl,
      },
      null,
      2,
    ),
    "utf8",
  );
}

main().catch(async (error) => {
  await fs.mkdir(path.dirname(OUTPUT_PATH), { recursive: true });
  await fs.writeFile(
    OUTPUT_PATH,
    JSON.stringify(
      {
        completedAt: new Date().toISOString(),
        webUrl: WEB_URL,
        status: "failed",
        error: error instanceof Error ? error.message : String(error),
      },
      null,
      2,
    ),
    "utf8",
  );
  console.error(error);
  process.exitCode = 1;
});
