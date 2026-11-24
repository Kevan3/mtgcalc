// Builds the Rust core for the browser (ADR-0013 §6):
//   1. cargo build --target wasm32-unknown-unknown --release -p mtgcalc-wasm
//   2. wasm-bindgen --target web  ->  src/wasm-pkg/
// The wasm-bindgen CLI must be exactly the version of the wasm-bindgen crate; this
// script checks that first, because a mismatch fails in confusing ways.
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const web = dirname(dirname(fileURLToPath(import.meta.url)));
const native = join(web, "..", "native");
const out = join(web, "src", "wasm-pkg");
const target = "wasm32-unknown-unknown";

const manifest = readFileSync(join(native, "wasm", "Cargo.toml"), "utf8");
const pinned = /wasm-bindgen = "=([0-9.]+)"/.exec(manifest)?.[1];
if (!pinned) throw new Error("native/wasm/Cargo.toml must pin wasm-bindgen with '='");
const install = `cargo install wasm-bindgen-cli --version ${pinned} --locked`;

let cli;
try {
  cli = execFileSync("wasm-bindgen", ["--version"], { encoding: "utf8" }).trim().split(" ")[1];
} catch {
  throw new Error(`wasm-bindgen CLI not found; install it with: ${install}`);
}
if (cli !== pinned) {
  throw new Error(`wasm-bindgen CLI ${cli} does not match the crate (${pinned}): ${install}`);
}

execFileSync("cargo", ["build", "--release", "--target", target, "-p", "mtgcalc-wasm"], {
  cwd: native,
  stdio: "inherit",
});
rmSync(out, { recursive: true, force: true });
const built = join(native, "target", target, "release", "mtgcalc_wasm.wasm");
execFileSync("wasm-bindgen", ["--target", "web", "--out-dir", out, built], { stdio: "inherit" });

const bytes = readFileSync(join(out, "mtgcalc_wasm_bg.wasm"));
const kb = (n) => `${(n / 1024).toFixed(0)} kB`;
console.log(`mtgcalc_wasm_bg.wasm: ${kb(bytes.length)} (${kb(gzipSync(bytes).length)} gzip)`);
