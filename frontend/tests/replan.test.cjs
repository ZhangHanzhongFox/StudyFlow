const { after, before, beforeEach, afterEach, test } = require("node:test");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { createServer } = require("node:net");
const path = require("node:path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "../..");
const fixture = require(path.join(root, "data/scenarios/replan_acceptance.json"));
let api, apiUrl, vite, browser, context, page, siteUrl;
let pageErrors;

async function availablePort() {
  const server = createServer().listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

async function get(resource) {
  const response = await fetch(`${apiUrl}/${resource}`);
  assert.equal(response.status, 200);
  return response.json();
}

async function waitFor(check, message) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  assert.fail(message);
}

function taskRow(name) {
  return page.locator(".task-action-list article").filter({ has: page.getByText(name, { exact: true }) });
}

async function openActions() {
  await page.getByText("Task status & actions", { exact: false }).click();
  await page.getByText("Add or edit calendar block", { exact: true }).click();
}

async function calendarForm(end = "2026-09-03T10:00") {
  await page.getByLabel("Title", { exact: true }).fill("Extra lecture");
  await page.getByLabel("Starts").fill("2026-09-03T09:00");
  await page.getByLabel("Ends").fill(end);
}

async function assertWriteControlsDisabled(taskName = "task-slides") {
  assert.equal(await page.locator(".generate-button").isDisabled(), true);
  assert.equal(await taskRow(taskName).getByRole("button", { name: "Complete", exact: true }).isDisabled(), true);
  assert.equal(await taskRow(taskName).getByRole("button", { name: "Missed", exact: true }).isDisabled(), true);
  assert.equal(await page.getByLabel("Title", { exact: true }).isDisabled(), true);
  assert.equal(await page.locator(".calendar-submit").isDisabled(), true);
}

async function assertPreserved() {
  const schedule = await get("schedule");
  for (const id of ["task-research", "task-independent"]) {
    assert.deepEqual(schedule.find((item) => item.task_id === id),
      fixture.initial_state.scheduled_tasks.find((item) => item.task_id === id));
  }
  assert.equal((await get("tasks")).find((task) => task.id === "task-research").status, "completed");
}

function holdPost(endpoint) {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  let seen;
  const started = new Promise((resolve) => { seen = resolve; });
  const installed = page.route(`**/api/${endpoint}`, async (route) => {
    seen();
    await held;
    await route.continue();
  }, { times: 1 });
  return { installed, started, release };
}

before(async () => {
  const port = await availablePort();
  apiUrl = `http://127.0.0.1:${port}`;
  api = spawn(process.env.STUDYFLOW_TEST_PYTHON || path.join(root, ".venv/bin/python"),
    [path.join(__dirname, "acceptance_server.py"), "--port", String(port)],
    { cwd: root, stdio: ["ignore", "ignore", "inherit"] });
  await waitFor(async () => {
    try { return (await fetch(`${apiUrl}/health`)).ok; } catch { return false; }
  }, "Test API did not start");
  const { createServer: createViteServer } = await import("vite");
  vite = await createViteServer({
    root: path.join(root, "frontend"),
    server: { host: "127.0.0.1", port: 0, open: false,
      proxy: { "/api": { target: apiUrl, rewrite: (url) => url.replace(/^\/api/, "") } } },
  });
  await vite.listen();
  siteUrl = `http://127.0.0.1:${vite.httpServer.address().port}`;
  browser = await chromium.launch({
    headless: true,
    ...(process.env.STUDYFLOW_TEST_BROWSER ? { executablePath: process.env.STUDYFLOW_TEST_BROWSER } : {}),
  });
});

beforeEach(async () => {
  assert.equal((await fetch(`${apiUrl}/test/reset`, { method: "POST" })).status, 200);
  context = await browser.newContext({ locale: "en-US", timezoneId: "Asia/Singapore", viewport: { width: 1440, height: 1000 } });
  page = await context.newPage();
  pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.clock.setFixedTime(new Date("2026-09-03T09:00:00+08:00"));
  await page.goto(siteUrl);
  await page.getByText("Task status & actions", { exact: false }).waitFor();
  await openActions();
});

afterEach(async () => {
  await context?.close();
  assert.deepEqual(pageErrors, []);
});

after(async () => {
  await browser?.close();
  await vite?.close();
  if (api && api.exitCode === null) {
    api.kill("SIGTERM");
    await once(api, "exit");
  }
});

test("missed work moves its dependents and locks other writes until refresh completes", async () => {
  await page.clock.setFixedTime(new Date(fixture.scenarios.missed.request.timestamp));
  const hold = holdPost("replan");
  await hold.installed;
  await taskRow("task-slides").getByRole("button", { name: "Missed", exact: true }).click();
  await hold.started;
  try { await assertWriteControlsDisabled(); } finally { hold.release(); }
  await page.getByText("Replan complete", { exact: true }).waitFor();
  assert.equal(await page.locator(".schedule-changes article").count(), 4);
  assert.equal(await page.locator(".change-kind.preserved").count(), 2);
  const preservedResearch = page.locator(".schedule-changes article").filter({ hasText: "task-research" });
  assert.match(await preservedResearch.innerText(), /preserved/i);
  assert.match(await preservedResearch.innerText(), /completed/i);
  const schedule = await get("schedule");
  for (const [id, start] of Object.entries(fixture.scenarios.missed.expected_start_times)) {
    assert.equal(schedule.find((item) => item.task_id === id).start_time, start);
  }
  await assertPreserved();
  assert.equal((await get("planning-events")).length, 1);
  assert.equal(await page.locator(".generate-button").isEnabled(), true);
});

test("calendar add and edit replan through the UI while preserving unrelated work", async () => {
  await calendarForm();
  await page.getByRole("button", { name: "Add & replan" }).click();
  await page.getByText("Replan complete", { exact: true }).waitFor();
  const blocks = await get("calendar-blocks");
  assert.equal(blocks.length, 1);
  const schedule = await get("schedule");
  for (const [id, start] of Object.entries(fixture.scenarios.calendar_changed.expected_start_times)) {
    assert.equal(schedule.find((item) => item.task_id === id).start_time, start);
  }
  await assertPreserved();
  await page.getByLabel("Calendar entry").selectOption(blocks[0].id);
  await page.getByLabel("Ends").fill("2026-09-03T11:00");
  await page.getByRole("button", { name: "Update & replan" }).click();
  await waitFor(async () => (await get("planning-events")).length === 2, "Calendar update was not saved");
  await page.getByText("Replan complete", { exact: true }).waitFor();
  assert.equal((await get("calendar-blocks")).length, 1);
  assert.equal(new Date((await get("calendar-blocks"))[0].end_time).toISOString(), "2026-09-03T03:00:00.000Z");
  await assertPreserved();
});

test("no remaining slot shows explicit unscheduled reasons instead of hiding failed work", async () => {
  await calendarForm("2026-09-03T18:00");
  await page.getByRole("button", { name: "Add & replan" }).click();
  await page.getByText("3 task(s) could not be scheduled", { exact: false }).waitFor();
  assert.equal(await page.locator(".operation-failures article").count(), 3);
  assert.match(await page.locator(".operation-failures").innerText(), /deadline constraint/i);
  assert.match(await page.locator(".operation-failures").innerText(), /dependency conflict/i);
  assert.deepEqual((await get("schedule")).map((item) => item.task_id), ["task-research"]);
});

test("complete updates task status and keeps completed placements", async () => {
  await taskRow("task-slides").getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByText("Replan complete", { exact: true }).waitFor();
  assert.equal((await get("tasks")).find((task) => task.id === "task-slides").status, "completed");
  assert.equal(await taskRow("task-slides").getByRole("button", { name: "Missed", exact: true }).isDisabled(), true);
  await assertPreserved();
});

test("rejected calendar writes retain the last comparison and unscheduled reasons", async () => {
  await calendarForm("2026-09-03T18:00");
  await page.getByRole("button", { name: "Add & replan" }).click();
  await page.getByText("3 task(s) could not be scheduled", { exact: false }).waitFor();
  const failures = await page.locator(".operation-failures").innerText();
  const changes = await page.locator(".schedule-changes article").allTextContents();
  await page.getByLabel("Ends").fill("2026-09-03T08:00");
  await page.getByRole("button", { name: "Add & replan" }).click();
  await page.getByText("Replan failed", { exact: true }).waitFor();
  assert.equal(await page.locator(".operation-failures").innerText(), failures);
  assert.deepEqual(await page.locator(".schedule-changes article").allTextContents(), changes);
  assert.match(await page.locator(".replan-notice-heading").innerText(), /body/);
});

test("Generate Plan displays the specific API error and retains saved replan details", async () => {
  await taskRow("task-slides").getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByText("Replan complete", { exact: true }).waitFor();
  const changes = await page.locator(".schedule-changes").innerText();
  await page.route("**/api/plan", (route) => route.fulfill({ status: 500, json: {
    detail: { code: "planning_failed", message: "The planning pipeline could not complete." },
  } }));
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Regenerate Plan", exact: true }).click();
  await page.getByText("Plan update failed", { exact: true }).waitFor();
  assert.match(await page.locator(".change-notice").innerText(), /The planning pipeline could not complete/);
  assert.equal(await page.locator(".schedule-changes").innerText(), changes);
});

test("schedule changes show the next day's date when missed work cannot fit tonight", async () => {
  assert.equal((await fetch(`${apiUrl}/test/reset?extended_deadline=true`, { method: "POST" })).status, 200);
  await page.clock.setFixedTime(new Date("2026-09-03T21:30:00+08:00"));
  await page.reload();
  await openActions();
  await taskRow("task-slides").getByRole("button", { name: "Missed", exact: true }).click();
  await page.getByText("Replan complete", { exact: true }).waitFor();
  assert.match(await page.locator(".schedule-changes").innerText(), /Sep 4/);
  assert.equal((await get("schedule")).find((item) => item.task_id === "task-slides").start_time,
    "2026-09-04T08:00:00+08:00");
  await assertPreserved();
});

test("regeneration requires consent, locks task/calendar writes, and clears old replan results", async () => {
  // Generated tasks have different IDs from the handoff fixture. Exercise the
  // real Plan -> Complete -> Regenerate path so event references stay valid.
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Regenerate Plan", exact: true }).click();
  await page.getByText("Plan updated", { exact: true }).waitFor();
  const generatedTasks = await get("tasks");
  const first = generatedTasks.find((task) => task.dependencies.length === 0);
  const other = generatedTasks.find((task) => task.id !== first.id);
  await taskRow(first.name).getByRole("button", { name: "Complete", exact: true }).click();
  await page.getByText("Replan complete", { exact: true }).waitFor();
  const before = await get("tasks");
  assert.equal(before.find((task) => task.id === first.id).status, "completed");
  let posts = 0;
  page.on("request", (request) => { if (request.url().endsWith("/api/plan") && request.method() === "POST") posts++; });
  page.once("dialog", async (dialog) => {
    assert.match(dialog.message(), /reset task progress, including completed work/);
    await dialog.dismiss();
  });
  await page.getByRole("button", { name: "Regenerate Plan", exact: true }).click();
  assert.equal(posts, 0);
  assert.deepEqual(await get("tasks"), before);
  const hold = holdPost("plan");
  await hold.installed;
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Regenerate Plan", exact: true }).click();
  await hold.started;
  try { await assertWriteControlsDisabled(other.name); } finally { hold.release(); }
  await page.getByText("Plan updated", { exact: true }).waitFor();
  assert.equal(posts, 1);
  assert.equal(await page.locator(".schedule-changes article").count(), 0);
  assert.equal((await get("tasks")).some((task) => task.status === "completed"), false);
  assert.equal(await page.getByLabel("Title", { exact: true }).isEnabled(), true);
});

for (const kind of ["replan", "plan"]) {
  test(`${kind}: successful write followed by failed GET retries reads only`, async () => {
    let writeSaved = false;
    let failRead = true;
    let posts = 0;
    await page.route(`**/api/${kind}`, async (route) => {
      posts++;
      const response = await route.fetch();
      assert.equal(response.status(), 200);
      writeSaved = true;
      await route.fulfill({ response });
    });
    await page.route("**/api/tasks", async (route) => {
      if (writeSaved && failRead) {
        failRead = false;
        await route.fulfill({ status: 503, json: { detail: { message: "test read failure" } } });
      } else await route.continue();
    });
    if (kind === "plan") {
      page.once("dialog", (dialog) => dialog.accept());
      await page.getByRole("button", { name: "Regenerate Plan", exact: true }).click();
      await page.getByText("Plan saved — refresh needed", { exact: true }).waitFor();
    } else {
      await taskRow("task-slides").getByRole("button", { name: "Missed", exact: true }).click();
      await page.getByText("Saved — refresh needed", { exact: true }).waitFor();
    }
    await assertWriteControlsDisabled();
    await page.getByRole("button", { name: "Retry refresh", exact: true }).click();
    await page.getByText(kind === "plan" ? "Plan updated" : "Replan complete", { exact: true }).waitFor();
    assert.equal(posts, 1);
    assert.equal(await page.locator(".generate-button").isEnabled(), true);
  });
}

test("failed write releases controls; retry uses the original event and saves it once", async () => {
  const sentEvents = [];
  await page.route("**/api/replan", async (route) => {
    sentEvents.push(route.request().postDataJSON());
    if (sentEvents.length === 1) await route.fulfill({ status: 503, json: { detail: { code: "test_failure", message: "Try again" } } });
    else await route.continue();
  });
  await taskRow("task-slides").getByRole("button", { name: "Missed", exact: true }).click();
  await page.getByText("Replan failed", { exact: true }).waitFor();
  assert.equal(await page.locator(".generate-button").isEnabled(), true);
  await page.getByRole("button", { name: "Retry action", exact: true }).click();
  await page.getByText("Replan complete", { exact: true }).waitFor();
  assert.equal(sentEvents.length, 2);
  assert.equal(sentEvents[0].id, sentEvents[1].id);
  assert.equal((await get("planning-events")).length, 1);
});

test("lost write response recovers the saved event without submitting it again", async () => {
  let posts = 0;
  await page.route("**/api/replan", async (route) => {
    posts++;
    const response = await route.fetch();
    assert.equal(response.status(), 200);
    await route.abort("failed");
  });
  await taskRow("task-slides").getByRole("button", { name: "Missed", exact: true }).click();
  await page.getByText("Replan failed", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Retry action", exact: true }).click();
  await page.getByText("Replan complete", { exact: true }).waitFor();
  assert.equal(posts, 1);
  assert.equal((await get("planning-events")).length, 1);
});

test("default runtime generates today's sessions even when mock calendar dates are in the past", async () => {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    url.pathname = url.pathname.replace("/api/", "/api/live/");
    await route.continue({ url: url.toString() });
  });
  await page.clock.setFixedTime(new Date("2026-09-04T01:00:00+08:00"));
  await page.reload();
  await page.getByRole("button", { name: "Generate Plan", exact: true }).click();
  await page.getByText("Plan updated", { exact: true }).waitFor();
  assert.ok(await page.locator(".timeline-item").count() > 0);
  const response = await fetch(`${apiUrl}/live/schedule`);
  const schedule = await response.json();
  assert.equal(schedule[0].start_time, "2026-09-04T08:00:00+08:00");
  assert.ok(schedule.every((item) => Date.parse(item.start_time) >= Date.parse("2026-09-04T01:00:00+08:00")));
});
