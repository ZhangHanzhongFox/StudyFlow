import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";

// Load the actual TypeScript client through Vite; no API, browser, or reset endpoint.
const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const { code } = await transformWithEsbuild(source, "api.ts", {
  loader: "ts", format: "esm", define: { "import.meta.env": "{}" },
});
const { compareSchedules, generatePlan, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

const placement = (task_id, overrides = {}) => ({
  id: `placement-${task_id}`, task_id,
  start_time: "2026-09-04T09:00:00+08:00",
  end_time: "2026-09-04T10:00:00+08:00", flexibility: "flexible",
  ...overrides,
});

test("comparison distinguishes preserved, moved, added and removed by task identity", () => {
  const completed = placement("completed");
  const unrelated = placement("unrelated");
  const moved = placement("moved");
  const removed = placement("removed");
  const next = placement("moved", {
    start_time: "2026-09-05T09:00:00+08:00", end_time: "2026-09-05T10:00:00+08:00",
  });
  const added = placement("added");
  const result = compareSchedules([completed, unrelated, moved, removed], [completed, unrelated, next, added]);
  assert.deepEqual(result.preserved, [completed, unrelated]);
  assert.deepEqual(result.moved, [next]);
  assert.deepEqual(result.added, [added]);
  assert.deepEqual(result.removed, [removed]);
});

test("equivalent timestamp offsets and a changed placement ID remain preserved", () => {
  const before = placement("same");
  const after = placement("same", {
    id: "replacement-placement-id", start_time: "2026-09-04T01:00:00Z", end_time: "2026-09-04T02:00:00Z",
  });
  assert.deepEqual(compareSchedules([before], [after]).preserved, [after]);
});

test("flexibility-only and end-time changes are not incorrectly preserved", () => {
  for (const change of [{ flexibility: "hard" }, { end_time: "2026-09-04T11:00:00+08:00" }]) {
    const before = placement("same");
    const after = placement("same", change);
    const result = compareSchedules([before], [after]);
    assert.equal(result.preserved.length, 0);
    assert.deepEqual(result.moved, [after]);
  }
});

test("empty schedules have empty comparisons", () => {
  assert.deepEqual(compareSchedules([], []), { added: [], moved: [], preserved: [], removed: [] });
});

test("Generate Plan preserves FastAPI 422 field locations and validation messages", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ detail: [
    { loc: ["body", "calendar_block", "end_time"], msg: "Must be after start_time" },
    { loc: ["body", "tasks", 0, "name"], msg: "Field required" },
  ] }), { status: 422 }));
  await assert.rejects(generatePlan(new AbortController().signal), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 422);
    assert.equal(error.code, "validation_error");
    assert.equal(error.message, "body.calendar_block.end_time: Must be after start_time; body.tasks.0.name: Field required");
    return true;
  });
});

for (const status of [409, 500, 501]) {
  test(`structured ${status} messages and codes survive unchanged`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({
      detail: { code: "backend_code", message: "Backend explanation" },
    }), { status }));
    await assert.rejects(generatePlan(new AbortController().signal), (error) => {
      assert.equal(error.status, status);
      assert.equal(error.code, "backend_code");
      assert.equal(error.message, "Backend explanation");
      return true;
    });
  });
}
