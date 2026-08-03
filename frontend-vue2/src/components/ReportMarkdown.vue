<template>
  <div class="report-markdown" v-html="html" />
</template>

<script>
import { translateDisplayText } from "../lib/labels";

export default {
  name: "ReportMarkdown",
  props: {
    text: { type: String, default: "" },
  },
  computed: {
    html() {
      return translateDisplayText(this.text)
        .split(/\r?\n/)
        .map((rawLine) => renderLine(rawLine.trim()))
        .join("");
    },
  },
};

function renderLine(line) {
  if (!line) return '<div class="report-space"></div>';
  if (line === "---") return "<hr>";
  if (line.startsWith("### ")) return `<h3>${inline(line.slice(4))}</h3>`;
  if (line.startsWith("## ")) return `<h2>${inline(line.slice(3))}</h2>`;
  if (line.startsWith("# ")) return `<h1>${inline(line.slice(2))}</h1>`;
  if (/^\d+\.\s+/.test(line)) return `<p class="report-numbered">${inline(line)}</p>`;
  if (line.startsWith("- ")) return `<p class="report-bullet">${inline(line.slice(2))}</p>`;
  return `<p>${inline(line)}</p>`;
}

function inline(value) {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function escapeHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
</script>
