const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");
const createDOMPurify = require("dompurify");

const bundled = fs.readFileSync(path.join(__dirname, "..", "..", "app", "lib", "purify.min.js"), "utf8");
if (!bundled.includes("DOMPurify 3.4.17")) {
  console.error("El archivo entregado no es DOMPurify 3.4.17");
  process.exit(1);
}

const { window } = new JSDOM("<!DOCTYPE html><html><body></body></html>");
const DOMPurify = createDOMPurify(window);
const dirty = '<img src=x onerror=alert(1)><script>alert(1)</script><strong>ok</strong><a href="https://evil">x</a>';
const clean = DOMPurify.sanitize(dirty, {
  ALLOWED_TAGS: ["strong", "em", "br", "p", "ul", "ol", "li", "code"],
  ALLOWED_ATTR: [],
});
if (clean.includes("onerror") || clean.includes("<script") || clean.includes("<a ") || clean.includes("<img")) {
  console.error("Sanitizado inesperado:", clean);
  process.exit(1);
}
if (!clean.includes("<strong>ok</strong>")) {
  console.error("Se perdio el marcado permitido:", clean);
  process.exit(1);
}
console.log("chat sanitize ok:", clean);
