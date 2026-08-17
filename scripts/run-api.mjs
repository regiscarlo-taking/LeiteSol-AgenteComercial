import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const apiSrcPath = path.join(projectRoot, "apps", "api", "src");
const apiPackagesPath = path.join(projectRoot, "apps", "api", ".python_packages");
const localVenvPython = path.join(projectRoot, "apps", "api", ".venv", "Scripts", "python.exe");
const defaultHost = "0.0.0.0";
const defaultPort = "5000";

const parseArgs = (argv) => {
  const options = {
    host: defaultHost,
    port: defaultPort,
    reload: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index];

    if (current === "--reload") {
      options.reload = true;
      continue;
    }

    if (current === "--no-reload") {
      options.reload = false;
      continue;
    }

    if (current === "--host" && argv[index + 1]) {
      options.host = argv[index + 1];
      index += 1;
      continue;
    }

    if (current === "--port" && argv[index + 1]) {
      options.port = argv[index + 1];
      index += 1;
    }
  }

  return options;
};

const options = parseArgs(process.argv.slice(2));

const withPythonPath = () => ({
  ...process.env,
  PORT: process.env.PORT ?? options.port,
  PYTHONPATH: [apiSrcPath, apiPackagesPath, process.env.PYTHONPATH]
    .filter(Boolean)
    .join(path.delimiter),
});

const hasCommand = (command, args = ["--version"]) => {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    shell: true,
    stdio: "ignore",
  });

  return result.status === 0;
};

const run = (command, args, env = process.env) =>
  spawn(command, args, {
    cwd: projectRoot,
    shell: true,
    stdio: "inherit",
    env,
  });

const uvicornArgs = [
  "-m",
  "uvicorn",
  "leitesol_api.main:app",
  "--host",
  options.host,
  "--port",
  process.env.PORT ?? options.port,
  ...(options.reload ? ["--reload"] : []),
];

if (hasCommand("uv")) {
  const child = run("uv", [
    "run",
    "--package",
    "leitesol-api",
    "python",
    ...uvicornArgs,
  ]);

  child.on("exit", (code) => process.exit(code ?? 0));
  process.on("SIGINT", () => child.kill("SIGINT"));
  process.on("SIGTERM", () => child.kill("SIGTERM"));
} else if (existsSync(localVenvPython) && existsSync(apiPackagesPath)) {
  const child = run(localVenvPython, uvicornArgs, withPythonPath());

  child.on("exit", (code) => process.exit(code ?? 0));
  process.on("SIGINT", () => child.kill("SIGINT"));
  process.on("SIGTERM", () => child.kill("SIGTERM"));
} else if (hasCommand("py", ["-3.12", "--version"]) && existsSync(apiPackagesPath)) {
  const child = run("py", ["-3.12", ...uvicornArgs], withPythonPath());

  child.on("exit", (code) => process.exit(code ?? 0));
  process.on("SIGINT", () => child.kill("SIGINT"));
  process.on("SIGTERM", () => child.kill("SIGTERM"));
} else {
  console.error("Nao foi possivel iniciar a API.");
  console.error("Opcoes para destravar:");
  console.error("1. Instale o uv e execute `npm run dev:api` novamente.");
  console.error("2. Ou prepare um ambiente Python local em `apps/api/.venv` com `uvicorn` instalado.");
  console.error("3. Ou rode apenas frontend + gateway com `npm run dev`.");
  process.exit(1);
}
