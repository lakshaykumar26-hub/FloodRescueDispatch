import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: [
      "lib/**/*.test.{ts,tsx}",
      "components/**/*.test.{ts,tsx}",
      "hooks/**/*.test.{ts,tsx}",
      "app/**/*.test.{ts,tsx}",
    ],
    css: false,
    testTimeout: 10000,
  },
});
