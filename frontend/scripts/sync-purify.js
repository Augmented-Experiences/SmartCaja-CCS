const fs = require("fs");
const path = require("path");

const src = path.join(__dirname, "..", "node_modules", "dompurify", "dist", "purify.min.js");
const dest = path.join(__dirname, "..", "..", "app", "lib", "purify.min.js");
let text = fs.readFileSync(src, "utf8");
text = text.replace(/\n\/\/# sourceMappingURL=purify\.min\.js\.map\s*$/, "\n");
fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.writeFileSync(dest, text);
const version = (text.match(/DOMPurify (\d+\.\d+\.\d+)/) || [])[1];
if (version !== "3.4.17") {
  console.error("Version inesperada de DOMPurify:", version);
  process.exit(1);
}
console.log("app/lib/purify.min.js <- DOMPurify", version);
