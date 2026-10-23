// Construit le moteur Python en un exécutable unique, au nom attendu par Tauri
// (src-tauri/binaries/openmedia-backend-<triplet>.exe), avant `tauri build`.
//
//   npm run sidecar
//   npm run tauri build -- --config src-tauri/tauri.bundle.conf.json

import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.join(root, "backend");
const triple = execSync("rustc --print host-tuple").toString().trim();
const sep = process.platform === "win32" ? ";" : ":";

const args = [
  "run", "pyinstaller", "sidecar.py",
  "--onefile", "--noconsole", "--noconfirm", "--clean",
  "--name", `openmedia-backend-${triple}`,
  "--distpath", path.join(root, "src-tauri", "binaries"),
  "--workpath", path.join(backend, "build"),
  "--specpath", path.join(backend, "build"),
  "--collect-submodules", "uvicorn",
  "--collect-all", "trafilatura",
  "--collect-all", "justext",
  "--collect-data", "tldextract",
  "--collect-data", "certifi",
  "--add-data", `${path.join(backend, "openmedia", "prompts")}${sep}openmedia/prompts`,
  "--add-data", `${path.join(backend, "openmedia", "sources", "seed_sources.yaml")}${sep}openmedia/sources`,
];

execSync(`python -m uv ${args.map((a) => JSON.stringify(a)).join(" ")}`, { cwd: backend, stdio: "inherit" });
console.log(`\nSidecar prêt : src-tauri/binaries/openmedia-backend-${triple}.exe`);
