import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  publicDir: fileURLToPath(new URL("../web/public", import.meta.url)),
});
