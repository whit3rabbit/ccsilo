"""Node.js compatibility prelude for unpacked Bun entry modules."""

BUN_NODE_COMPAT_MARKER = "/* cc-extractor:bun-node-compat */"

BUN_NODE_COMPAT_PRELUDE = r'''/* cc-extractor:bun-node-compat */
;(function(){
  if (typeof globalThis.Bun === "object" && globalThis.Bun && globalThis.Bun.__ccExtractorNodeCompat) return;
  const req = typeof require === "function" ? require : null;
  const nodeCrypto = req ? req("crypto") : null;
  const childProcess = req ? req("child_process") : null;
  const fs = req ? req("fs") : null;
  const yamlModule = req ? (function(){try{return req("yaml");}catch{return null;}})() : null;
  const ansiPattern = /[\x1B\x9B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[a-zA-Z\d]*)*)?\x07)|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g;
  function stripANSI(value){return String(value == null ? "" : value).replace(ansiPattern,"");}
  function isCombining(cp){return cp>=0x0300&&cp<=0x036f||cp>=0x1ab0&&cp<=0x1aff||cp>=0x1dc0&&cp<=0x1dff||cp>=0x20d0&&cp<=0x20ff||cp>=0xfe20&&cp<=0xfe2f||cp>=0xfe00&&cp<=0xfe0f||cp===0x200d;}
  function isWide(cp){return cp>=0x1100&&(cp<=0x115f||cp===0x2329||cp===0x232a||cp>=0x2e80&&cp<=0xa4cf&&cp!==0x303f||cp>=0xac00&&cp<=0xd7a3||cp>=0xf900&&cp<=0xfaff||cp>=0xfe10&&cp<=0xfe19||cp>=0xfe30&&cp<=0xfe6f||cp>=0xff00&&cp<=0xff60||cp>=0xffe0&&cp<=0xffe6||cp>=0x1f300&&cp<=0x1faff||cp>=0x20000&&cp<=0x3fffd);}
  function stringWidth(value){
    let width = 0;
    for (const char of stripANSI(value)){
      const cp = char.codePointAt(0);
      if (cp === 0 || cp < 32 || cp >= 0x7f && cp < 0xa0 || isCombining(cp)) continue;
      width += isWide(cp) ? 2 : 1;
    }
    return width;
  }
  function wrapAnsi(value, columns){
    const text = String(value == null ? "" : value);
    const limit = Number(columns);
    if (!Number.isFinite(limit) || limit <= 0) return text;
    return text.split("\n").map((line) => {
      let out = "";
      let width = 0;
      for (const char of line){
        const w = stringWidth(char);
        if (width > 0 && width + w > limit){out += "\n"; width = 0;}
        out += char;
        width += w;
      }
      return out;
    }).join("\n");
  }
  function hash(value, seed){
    const h = nodeCrypto.createHash("sha256");
    if (seed !== undefined) h.update(String(seed));
    h.update(typeof value === "string" || Buffer.isBuffer(value) ? value : JSON.stringify(value));
    const hex = h.digest("hex").slice(0,16);
    return BigInt("0x" + hex);
  }
  function which(command){
    if (!command || !childProcess) return null;
    const cmd = process.platform === "win32" ? "where" : "command";
    const args = process.platform === "win32" ? [command] : ["-v", command];
    const result = childProcess.spawnSync(cmd, args, {encoding:"utf8", shell:process.platform !== "win32", stdio:["ignore","pipe","ignore"], timeout:1000});
    if (result.status !== 0 || !result.stdout) return null;
    return result.stdout.split(/\r?\n/).find(Boolean) || null;
  }
  function unsupported(name){return function(){throw new Error("Bun."+name+" is not supported in cc-extractor Node runtime");};}
  const semver = {
    order(a,b){
      const pa = String(a).split(/[.+-]/).map((part) => /^\d+$/.test(part) ? Number(part) : part);
      const pb = String(b).split(/[.+-]/).map((part) => /^\d+$/.test(part) ? Number(part) : part);
      const len = Math.max(pa.length, pb.length);
      for (let i = 0; i < len; i++){
        const x = pa[i] == null ? 0 : pa[i], y = pb[i] == null ? 0 : pb[i];
        if (x === y) continue;
        if (typeof x === "number" && typeof y === "number") return x > y ? 1 : -1;
        return String(x) > String(y) ? 1 : -1;
      }
      return 0;
    },
    satisfies(){return true;}
  };
  const YAML = {
    parse(value){
      if (yamlModule && typeof yamlModule.parse === "function") return yamlModule.parse(value);
      try { return JSON.parse(value); }
      catch { throw new Error("Bun.YAML.parse is not available in cc-extractor Node runtime"); }
    },
    stringify(value){
      if (yamlModule && typeof yamlModule.stringify === "function") return yamlModule.stringify(value);
      return JSON.stringify(value, null, 2);
    }
  };
  const JSONL = {
    parseChunk(value){
      const values = [];
      const text = Buffer.isBuffer(value) ? value.toString("utf8") : String(value || "");
      for (const line of text.split(/\r?\n/)){if (line.trim()) values.push(JSON.parse(line));}
      return {values, done:true, error:null, read:text.length};
    }
  };
  class Transpiler {
    constructor(){this.options = arguments[0] || {};}
    transformSync(source){return String(source);}
    scanImports(){return [];}
  }
  const BunCompat = Object.assign({}, globalThis.Bun || {}, {
    __ccExtractorNodeCompat:true,
    embeddedFiles:[],
    gc:function(){if (typeof globalThis.gc === "function") return globalThis.gc();},
    generateHeapSnapshot:function(){return new ArrayBuffer(0);},
    hash,
    JSONL,
    listen:unsupported("listen"),
    semver,
    spawn:function(command, options){
      if (!childProcess) throw new Error("child_process is unavailable");
      const args = Array.isArray(command) ? command : [command];
      const proc = childProcess.spawn(args[0], args.slice(1), options || {});
      proc.exited = new Promise((resolve) => proc.on("exit", (code) => resolve(code)));
      if (proc.stdout && typeof proc.stdout.text !== "function") proc.stdout.text = function(){return new Promise((resolve,reject) => {let data = ""; proc.stdout.setEncoding("utf8"); proc.stdout.on("data", (chunk) => data += chunk); proc.stdout.on("end", () => resolve(data)); proc.stdout.on("error", reject);});};
      return proc;
    },
    stringWidth,
    stripANSI,
    Terminal:unsupported("Terminal"),
    Transpiler,
    version:process.versions.node,
    which,
    wrapAnsi,
    YAML
  });
  if (fs && !BunCompat.file) BunCompat.file = function(path){return {text:function(){return fs.promises.readFile(path, "utf8");}, arrayBuffer:async function(){const b = await fs.promises.readFile(path); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);}};};
  globalThis.Bun = BunCompat;
})();
'''


def ensure_bun_node_compat(js: str) -> str:
    if BUN_NODE_COMPAT_MARKER in js:
        return js
    return BUN_NODE_COMPAT_PRELUDE + "\n" + js


def has_bun_node_compat(js: str) -> bool:
    return BUN_NODE_COMPAT_MARKER in js
