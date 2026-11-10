import { defineConfig } from "vite";

// Static site: relative base so it works at any path (e.g. https://user.github.io/repo/).
// Data files live in public/data/ and are produced by `fuelprice-build` (see README).
export default defineConfig({
  base: "./",
});
