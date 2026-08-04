import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("application source contains the finished research atlas", async () => {
  const [page, app, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/AtlasApp.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(page, /Research Connections Atlas/);
  assert.match(app, /Mapping the research landscape/);
  assert.match(app, /Give feedback/);
  assert.match(layout, /openGraph/);
  assert.doesNotMatch(`${page}${app}${layout}${packageJson}`, /codex-preview|react-loading-skeleton/);
});

test("ships required application data and social preview", async () => {
  for (const file of ["faculty.json", "topics.json", "faculty_topic_edges.json", "faculty_similarity_edges.json", "publications.json", "manifest.json"]) {
    const value = JSON.parse(await readFile(new URL(`../public/data/${file}`, import.meta.url), "utf8"));
    assert.ok(value);
  }
  const image = await readFile(new URL("../public/og.png", import.meta.url));
  assert.ok(image.length > 100_000);
});

test("corpus statistics are derived from the loaded data", async () => {
  const app = await readFile(new URL("../app/AtlasApp.tsx", import.meta.url), "utf8");
  assert.match(app, /data\.faculty\.length/);
  assert.match(app, /data\.topics\.length/);
  assert.match(app, /data\.publications\.length/);
  assert.match(app, /data\.facultyTopicEdges\.length/);
  assert.doesNotMatch(app, /1,246|127 researchers|18 themes|369 faculty links/);
});
