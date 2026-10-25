// Writes the token blocks of src/index.css from design/tokens.json.
// `node scripts/theme.mjs` rewrites them; `--check` exits 1 when they drift.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const tokensPath = `${root}design/tokens.json`;
const cssPath = `${root}src/index.css`;

const tokens = JSON.parse(readFileSync(tokensPath, "utf8"));
const [primary, secondary] = tokens.color.themes.map((t) => t.id);
if (primary !== "dark" || secondary !== "light") {
  throw new Error(`tokens.json themes must be [dark, light], got [${primary}, ${secondary}]`);
}

const themed = [
  ...tokens.color.tokens.map((t) => [`--color-${t.name}`, t.value]),
  ...tokens.shadow.tokens.map((t) => [`--${t.name}`, t.value]),
];
const valueIn = (v, theme) => (typeof v === "string" ? v : v[theme] ?? v.dark);

const dark = [
  `--font-sans: ${tokens.type.families.sans};`,
  `--font-mono: ${tokens.type.families.mono};`,
  ...themed.map(([name, v]) => `${name}: ${valueIn(v, "dark")};`),
];
const light = themed
  .filter(([, v]) => typeof v !== "string" && v.light !== undefined && v.light !== v.dark)
  .map(([name, v]) => `${name}: ${v.light};`);

function replaceBlock(css, id, lines) {
  const re = new RegExp(`(  /\\* tokens:${id}:begin[^\\n]*\\n)[\\s\\S]*?(  /\\* tokens:${id}:end \\*/)`);
  if (!re.test(css)) throw new Error(`index.css has no tokens:${id} markers`);
  return css.replace(re, (_, begin, end) => begin + lines.map((l) => `  ${l}\n`).join("") + end);
}

const current = readFileSync(cssPath, "utf8");
const next = replaceBlock(replaceBlock(current, "dark", dark), "light", light);

if (process.argv.includes("--check")) {
  if (next !== current) {
    console.error("src/index.css is out of step with design/tokens.json; run `npm run theme`.");
    process.exit(1);
  }
} else if (next !== current) {
  writeFileSync(cssPath, next);
}
