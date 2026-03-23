import { rm } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const distPath = path.resolve(process.cwd(), "dist");

await rm(distPath, { recursive: true, force: true });
