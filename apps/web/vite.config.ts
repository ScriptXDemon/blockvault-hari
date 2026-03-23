import { execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

type BuildMeta = {
  buildId: string;
  builtAt: string;
  gitSha: string;
  sourceHash: string;
};

const WEB_ROOT = __dirname;
const WORKSPACE_ROOT = path.resolve(__dirname, "../..");
const HASH_INPUTS = [
  path.resolve(WEB_ROOT, "src"),
  path.resolve(WEB_ROOT, "public"),
  path.resolve(WEB_ROOT, "index.html"),
  path.resolve(WEB_ROOT, "package.json"),
  path.resolve(WEB_ROOT, "tsconfig.json"),
  path.resolve(WEB_ROOT, "vite.config.ts"),
  path.resolve(WORKSPACE_ROOT, "packages", "ui"),
  path.resolve(WORKSPACE_ROOT, "packages", "contracts"),
  path.resolve(WORKSPACE_ROOT, "package.json"),
  path.resolve(WORKSPACE_ROOT, "package-lock.json"),
  path.resolve(WORKSPACE_ROOT, "tsconfig.base.json"),
];

function collectFiles(targetPath: string): string[] {
  const stats = statSync(targetPath);
  if (stats.isFile()) {
    return [targetPath];
  }
  const files: string[] = [];
  for (const entry of readdirSync(targetPath, { withFileTypes: true })) {
    if (["dist", "node_modules", ".git"].includes(entry.name)) {
      continue;
    }
    const entryPath = path.join(targetPath, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectFiles(entryPath));
    } else if (entry.isFile()) {
      files.push(entryPath);
    }
  }
  return files;
}

function resolveGitSha() {
  try {
    return execSync("git rev-parse --short HEAD", { cwd: WORKSPACE_ROOT, stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    return "nogit";
  }
}

function computeSourceHash() {
  const hash = createHash("sha256");
  const files = HASH_INPUTS.flatMap((input) => collectFiles(input)).sort();
  for (const filePath of files) {
    hash.update(path.relative(WORKSPACE_ROOT, filePath));
    hash.update("\0");
    hash.update(readFileSync(filePath));
    hash.update("\0");
  }
  return hash.digest("hex");
}

function createBuildMeta(): BuildMeta {
  const builtAt = new Date().toISOString();
  const gitSha = resolveGitSha();
  const sourceHash = computeSourceHash();
  const compactBuiltAt = builtAt.replace(/[-:.TZ]/g, "").slice(0, 14);
  return {
    buildId: `${gitSha}-${compactBuiltAt}-${sourceHash.slice(0, 12)}`,
    builtAt,
    gitSha,
    sourceHash,
  };
}

function buildMetaPlugin(buildMeta: BuildMeta): Plugin {
  return {
    name: "blockvault-build-meta",
    apply: "build" as const,
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "build-meta.json",
        source: JSON.stringify(buildMeta, null, 2),
      });
    },
    transformIndexHtml() {
      return [
        {
          tag: "meta",
          attrs: {
            name: "blockvault-build-id",
            content: buildMeta.buildId,
          },
        },
        {
          tag: "meta",
          attrs: {
            name: "blockvault-build-source-hash",
            content: buildMeta.sourceHash,
          },
        },
      ];
    },
  };
}

const buildMeta = createBuildMeta();

export default defineConfig({
  plugins: [react(), buildMetaPlugin(buildMeta)],
  define: {
    __BLOCKVAULT_BUILD_ID__: JSON.stringify(buildMeta.buildId),
    __BLOCKVAULT_BUILD_AT__: JSON.stringify(buildMeta.builtAt),
    __BLOCKVAULT_BUILD_GIT_SHA__: JSON.stringify(buildMeta.gitSha),
    __BLOCKVAULT_BUILD_SOURCE_HASH__: JSON.stringify(buildMeta.sourceHash),
  },
  build: {
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("ethers")) {
            return "vendor-ethers";
          }
          if (id.includes("@tanstack/react-query")) {
            return "vendor-query";
          }
          if (id.includes("react-router")) {
            return "vendor-router";
          }
          if (id.includes("react")) {
            return "vendor-react";
          }
          return "vendor";
        },
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
  },
});
