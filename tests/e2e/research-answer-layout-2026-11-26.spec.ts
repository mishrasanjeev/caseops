/**
 * BUG-001 (Ram, 2026-11-26): the research answer page showed the content on
 * the left with excessive unused space on the right, and headings, paragraphs
 * and sections did not keep consistent spacing. Each block had its own width
 * cap (65ch of three font sizes, max-w-3xl, or none) inside an uncapped
 * <main>.
 *
 * The tester's words become geometry on a real signed-in answer created
 * through the UI: the column is centred in <main>, every block shares the
 * column's two edges, the three parts are evenly spaced, spacing inside each
 * part is uniform, the heading sizes step down, and nothing scrolls sideways,
 * at 1280/1440/1920, at 1440 under 80-150% browser zoom, and at 375 on a phone.
 *
 * Production runs as the test-legal tester with the no-paid marker, so the
 * model call is the deterministic offline provider. Local runs seed the
 * Section 138 sources into the fresh e2e database first, because retrieval
 * needs an indexed statute and judgment to answer at all.
 */
import { expect, test, type Page } from "@playwright/test";

import { prepareTester, type TesterRuntime } from "./support/ram-bugs4";
import { seedLocalResearchSources } from "./support/research-local-sources";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

const QUESTION =
  "A cheque of Rs 5 lakh was dishonoured due to insufficient funds. What are the legal requirements, "
  + "notice period and procedure for filing a case under Section 138 of the Negotiable Instruments Act, 1881?";

// Browser zoom is emulated as the CSS viewport the zoomed window would have:
// a 1440px window at 125% lays out a 1152px viewport.
const DESKTOP_WIDTHS: { label: string; width: number }[] = [
  { label: "1280px", width: 1280 },
  { label: "1440px", width: 1440 },
  { label: "1920px", width: 1920 },
  ...[0.8, 0.9, 1.1, 1.25, 1.5].map((zoom) => ({
    label: `1440px at ${Math.round(zoom * 100)}%`, width: Math.round(1440 / zoom),
  })),
];

/** Ask the benchmark question through the UI and open the answer's permanent page. */
async function answerThroughTheUi(page: Page, runtime: TesterRuntime, phone = false): Promise<string> {
  if (runtime.local) await seedLocalResearchSources();
  await page.goto(`${runtime.web.origin}/app/research?tab=answer`);
  await expect(page.getByTestId("research-tool-answer")).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Legal question").fill(QUESTION);
  await page.getByRole("button", { name: "Get research answer" }).click();
  const answer = page.getByTestId("research-answer");
  const unavailable = page.getByTestId("research-answer-unavailable");
  await expect(answer.or(unavailable)).toBeVisible({ timeout: 180_000 });
  await expect(unavailable, "the benchmark must be answered from indexed sources").toHaveCount(0);
  await expectAnswerLayout(page, "/app/research", { phone });
  // On /app/research the answer is a document below the question card, not a card inside it.
  await expect.soft(page.getByTestId("research-answer-panel").getByTestId("research-answer")).toHaveCount(0);

  const permalink = page.getByTestId("research-answer-actions").getByRole("link", { name: "Permanent link" });
  const href = await permalink.getAttribute("href");
  expect(href).toMatch(/^\/app\/research\/answers\/[^/]+$/);
  await permalink.click();
  await expect(page).toHaveURL(new RegExp(`${href!.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`));
  await expect(page.getByTestId("research-answer")).toBeVisible();
  return href!;
}

type Box = { name: string; left: number; right: number; top: number; bottom: number };
type Layout = {
  columnTestId: string | null;
  columnMaxWidth: string;
  viewport: number;
  scrollWidth: number;
  main: Box;
  mainContent: { left: number; right: number };
  column: Box;
  blocks: Box[];
  parts: Box[];
  groups: { name: string; gaps: number[] }[];
  headingSizes: { part: number[]; subSection: number[]; authority: number[] };
  timelineRows: { cells: { top: number; bottom: number }[] }[];
};

async function measure(page: Page): Promise<Layout> {
  return page.evaluate(() => {
    const box = (name: string, element: Element) => {
      const rect = element.getBoundingClientRect();
      return { name, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    };
    const one = (selector: string, root: ParentNode = document) => {
      const found = root.querySelector(selector);
      if (!found) throw new Error(`Missing ${selector}`);
      return found;
    };
    const label = (element: Element) => element.getAttribute("data-testid")
      ?? `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}`;
    const children = (element: Element) => [...element.children].filter((child) => child.getBoundingClientRect().height > 0);
    const gaps = (element: Element) => {
      const kids = children(element).map((child) => child.getBoundingClientRect());
      return kids.slice(1).map((rect, index) => rect.top - kids[index].bottom);
    };
    const main = one("main#main");
    const style = getComputedStyle(main);
    const mainBox = box("main", main);
    // The column is whatever directly holds the answer document, so the
    // geometry (not a test id) decides whether the page is laid out right.
    const article = one('[data-testid="research-answer"]');
    const column = article.parentElement!;
    const parts = ["research-short-answer", "research-detailed", "research-authorities"]
      .map((id) => one(`[data-testid="${id}"]`, article));
    const subSections = [...article.querySelectorAll('[data-testid^="research-section-"]')];
    const cards = [...article.querySelectorAll('[data-testid="research-authority-card"]')];
    const blocks: Element[] = [
      ...children(column),
      ...children(article),
      ...parts.flatMap(children),
      ...subSections.flatMap(children),
      ...cards,
    ];
    const size = (element: Element) => parseFloat(getComputedStyle(element).fontSize);
    return {
      columnTestId: column.getAttribute("data-testid"),
      columnMaxWidth: getComputedStyle(column).maxWidth,
      viewport: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      main: mainBox,
      mainContent: {
        left: mainBox.left + parseFloat(style.paddingLeft),
        right: mainBox.right - parseFloat(style.paddingRight),
      },
      column: box("column", column),
      blocks: blocks.map((element, index) => box(`${index}:${label(element)}`, element)),
      parts: parts.map((element) => box(label(element), element)),
      groups: [
        { name: "column", gaps: gaps(column) },
        ...parts.map((part) => ({ name: label(part), gaps: gaps(part) })),
        ...subSections.map((section) => ({ name: label(section), gaps: gaps(section) })),
      ],
      headingSizes: {
        part: parts.map((part) => size(one("h3", part))),
        subSection: subSections.map((section) => size(one("h4", section))),
        authority: cards.map((card) => size(one("h4", card))),
      },
      timelineRows: [...article.querySelectorAll('[data-testid="research-timeline"] [role="row"]')]
        .filter((row) => row.getBoundingClientRect().height > 0 && row.querySelector('[role="cell"]'))
        .map((row) => ({ cells: [...row.querySelectorAll('[role="cell"]')].map((cell) => {
          const rect = cell.getBoundingClientRect();
          return { top: rect.top, bottom: rect.bottom };
        }) })),
    };
  });
}

/** Soft assertions: one run reports every geometric defect, and any of them fails the test. */
async function expectAnswerLayout(page: Page, at: string, options: { phone?: boolean } = {}) {
  await expect(page.getByTestId("research-answer")).toBeVisible();
  const layout = await measure(page);
  const detail = `${at} (viewport ${layout.viewport}px)`;

  // Balanced margins: the column sits in the middle of <main>.
  const leftGap = layout.column.left - layout.main.left;
  const rightGap = layout.main.right - layout.column.right;
  expect.soft(Math.abs(leftGap - rightGap), `${detail}: column is centred in <main> (left ${leftGap}, right ${rightGap})`)
    .toBeLessThanOrEqual(2);
  // One reading width: the column is as wide as its cap allows, never wider
  // than <main>'s content box (a phone gets the full width).
  expect.soft(layout.columnMaxWidth, `${detail}: the column has a reading-width cap`).toMatch(/^\d+(\.\d+)?px$/);
  const available = layout.mainContent.right - layout.mainContent.left;
  const expectedWidth = Math.min(parseFloat(layout.columnMaxWidth), available);
  expect.soft(Math.abs(layout.column.right - layout.column.left - expectedWidth),
    `${detail}: column width is min(cap ${layout.columnMaxWidth}, main ${available}px)`).toBeLessThanOrEqual(1);
  if (options.phone) {
    expect.soft(Math.abs(layout.column.left - layout.mainContent.left), `${detail}: column fills the phone width`).toBeLessThanOrEqual(1);
  }

  // One left and one right edge for every block, list, timeline, card and the actions box.
  const offEdge = layout.blocks
    .filter((block) => Math.abs(block.left - layout.column.left) > 1 || Math.abs(block.right - layout.column.right) > 1)
    .map((block) => `${block.name} [${block.left.toFixed(1)}, ${block.right.toFixed(1)}]`);
  expect.soft(offEdge, `${detail}: blocks off the column edges [${layout.column.left.toFixed(1)}, ${layout.column.right.toFixed(1)}]`).toEqual([]);
  for (const required of ["research-answer-actions", "research-timeline", "research-authority-card", "research-law-checked"]) {
    expect.soft(layout.blocks.some((block) => block.name.endsWith(`:${required}`)), `${detail}: measured ${required}`).toBe(true);
  }

  // Short answer -> detailed research -> authorities: equal vertical gaps.
  const [short, detailed, authorities] = layout.parts;
  const first = detailed.top - short.bottom;
  const second = authorities.top - detailed.bottom;
  expect.soft(first, `${detail}: parts are separated`).toBeGreaterThan(0);
  expect.soft(Math.abs(first - second), `${detail}: part gaps ${first} and ${second} are equal`).toBeLessThanOrEqual(1);

  // Consistent spacing inside every part and every numbered sub-section.
  for (const group of layout.groups) {
    if (group.gaps.length < 2) continue;
    const spread = Math.max(...group.gaps) - Math.min(...group.gaps);
    expect.soft(spread, `${detail}: ${group.name} sibling gaps ${group.gaps.map((gap) => gap.toFixed(1)).join(", ")}`)
      .toBeLessThanOrEqual(1);
  }

  // Part headings > numbered sub-sections > authority titles.
  const { part, subSection, authority } = layout.headingSizes;
  expect.soft(subSection.length && authority.length, `${detail}: sub-sections and authorities rendered`).toBeTruthy();
  expect.soft(Math.min(...part), `${detail}: part headings outrank sub-sections`).toBeGreaterThan(Math.max(...subSection));
  expect.soft(Math.min(...subSection), `${detail}: sub-sections outrank authority titles`).toBeGreaterThan(Math.max(...authority));

  // The timeline stacks on a phone instead of squeezing three columns.
  if (options.phone) {
    expect.soft(layout.timelineRows.length, `${detail}: timeline rows rendered`).toBeGreaterThan(0);
    for (const row of layout.timelineRows) {
      for (let index = 1; index < row.cells.length; index += 1) {
        expect.soft(row.cells[index].top, `${detail}: timeline cells stack`).toBeGreaterThanOrEqual(row.cells[index - 1].bottom - 1);
      }
    }
  }

  expect.soft(layout.scrollWidth - layout.viewport, `${detail}: no horizontal page scroll`).toBeLessThanOrEqual(1);
  // The holder is the shared reading column primitive, not a one-off wrapper.
  expect.soft(layout.columnTestId, `${detail}: the answer sits in the shared reading column`).toBe("research-answer-column");
}

test("BUG-001 research answer column is centred with shared edges and even spacing at 1280-1920px and 80-150% zoom", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const runtime = await prepareTester(page, request, baseURL, { width: 1440, height: 900 });
  const href = await answerThroughTheUi(page, runtime);
  for (const { label, width } of DESKTOP_WIDTHS) {
    await test.step(label, async () => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${runtime.web.origin}${href}`);
      await expect(page.getByTestId("research-answer")).toBeVisible();
      await expectAnswerLayout(page, `${href} at ${label}`);
    });
  }
});

test("[mobile] BUG-001 research answer fills a 375px phone with shared edges, a stacked timeline and no sideways scroll", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const runtime = await prepareTester(page, request, baseURL, { width: 375, height: 812 });
  const href = await answerThroughTheUi(page, runtime, true);
  await page.goto(`${runtime.web.origin}${href}`);
  await expect(page.getByTestId("research-answer")).toBeVisible();
  await expectAnswerLayout(page, `${href} at 375px`, { phone: true });
});
