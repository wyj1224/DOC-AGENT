const { defineConfig } = require("vite");
const vue = require("@vitejs/plugin-vue2");

module.exports = defineConfig({
  plugins: [vue()],
  server: { host: "127.0.0.1", port: 5175 },
  preview: { host: "127.0.0.1", port: 4175 },
});
