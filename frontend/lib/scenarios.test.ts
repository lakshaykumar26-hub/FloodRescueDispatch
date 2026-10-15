/** Scenario picker catalog stays in sync with scenarios/*.json. */
import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DEFAULT_SCENARIO, SCENARIOS } from "./scenarios";

// Routing-test fixture, not a runnable simulation.
const NON_RUNNABLE = new Set(["mini_graph.json", ".gitkeep"]);

describe("SCENARIOS", () => {
  it("has unique, non-empty names/labels/blurbs with a valid default", () => {
    expect(SCENARIOS.length).toBeGreaterThan(0);
    const names = SCENARIOS.map((s) => s.name);
    expect(new Set(names).size).toBe(names.length);
    for (const s of SCENARIOS) {
      expect(s.name.trim().length).toBeGreaterThan(0);
      expect(s.label.trim().length).toBeGreaterThan(0);
      expect(s.blurb.trim().length).toBeGreaterThan(0);
    }
    expect(names).toContain(DEFAULT_SCENARIO);
  });

  it("covers every runnable scenarios/*.json file", () => {
    const dir = resolve(__dirname, "../../scenarios");
    const files = readdirSync(dir).filter((f) => f.endsWith(".json") && !NON_RUNNABLE.has(f));
    expect(files.length).toBeGreaterThan(0);
    const names = new Set(SCENARIOS.map((s) => s.name));
    for (const file of files) {
      expect(names.has(file.replace(/\.json$/, "")), `missing picker entry for ${file}`).toBe(true);
    }
  });
});
