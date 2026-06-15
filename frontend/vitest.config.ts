import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Vitest runs separately from the production `vite build`. jsdom gives the
// React Testing Library a DOM; test files live next to their components as
// *.test.tsx and are excluded from the production typecheck (tsconfig.json).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
