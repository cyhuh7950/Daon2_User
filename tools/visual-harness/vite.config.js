import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// 저장소 루트의 node_modules(react 등)와 packages/ui를 쓰도록 파일 접근 범위를 루트까지 연다.
export default { root: here, server: { port: 5199, strictPort: true, host: "127.0.0.1", fs: { allow: [path.resolve(here, "../..")] } } };
