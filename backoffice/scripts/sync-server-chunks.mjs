import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const projectRoot = process.cwd();
const serverDir = join(projectRoot, ".next", "server");
const chunksDir = join(serverDir, "chunks");

if (!existsSync(serverDir) || !existsSync(chunksDir)) {
  process.exit(0);
}

mkdirSync(serverDir, { recursive: true });

for (const entry of readdirSync(chunksDir)) {
  const source = join(chunksDir, entry);
  if (!statSync(source).isFile() || !entry.endsWith(".js")) {
    continue;
  }

  const target = join(serverDir, entry);
  copyFileSync(source, target);
}

