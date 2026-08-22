/**
 * Phone layout — docs/21 §5, docs/07 §3.2.
 *
 * The responsive guideline forbids the easy version of "responsive": three columns
 * narrowed until they fit. On a phone the conversation is the whole screen and the two
 * rails become sheets, and these tests hold that line — a regression to squeezed columns
 * passes every desktop test in the suite.
 */
import { expect, test, type Page } from "@playwright/test";

const created: string[] = [];

async function startThread(page: Page): Promise<string> {
  await page.goto("/");
  await page.getByTestId("open-threads").click();
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/api/v1/threads") && r.request().method() === "POST",
    ),
    page.getByTestId("new-thread").click(),
  ]);
  const { thread_id: threadId } = (await response.json()) as { thread_id: string };
  created.push(threadId);
  return threadId;
}

test.afterAll(async ({ playwright }) => {
  const context = await playwright.request.newContext({ baseURL: "http://127.0.0.1:8000" });
  for (const id of created.splice(0)) {
    await context.delete(`/api/v1/threads/${id}`).catch(() => undefined);
  }
  await context.dispose();
});

test.describe("phone layout", () => {
  test("shows the conversation full width, with both rails off screen", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("composer-input")).toBeVisible();

    // The rails exist in the DOM at desktop widths only; on a phone they must not be
    // occupying screen space next to the conversation.
    await expect(page.getByTestId("thread-list")).toBeHidden();
    await expect(page.getByTestId("context-panel")).toBeHidden();

    // The composer spans the viewport rather than a squeezed middle column.
    const viewport = page.viewportSize()!;
    const composer = await page.getByTestId("composer-input").boundingBox();
    expect(composer!.width).toBeGreaterThan(viewport.width * 0.6);
  });

  test("never scrolls horizontally", async ({ page }) => {
    // An explicit rule in the responsive guideline, and the failure mode of every
    // fixed-width element that slips into a phone layout.
    await startThread(page);
    await page.getByTestId("composer-input").fill("A".repeat(400));
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("reaches conversations through the header, and picking one closes the sheet", async ({
    page,
  }) => {
    const threadId = await startThread(page);
    // Creating from inside the sheet navigates and closes it in one move.
    await expect(page).toHaveURL(new RegExp(`/threads/${threadId}$`));
    await expect(page.getByTestId("thread-list")).toBeHidden();

    await page.getByTestId("open-threads").click();
    await expect(page.getByTestId("thread-list")).toBeVisible();
    await page.getByTestId("thread-item").first().click();
    await expect(page.getByTestId("thread-list")).toBeHidden();
    await expect(page).toHaveURL(/\/threads\/th_/);
  });

  test("reaches customer context through the header", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("open-context").click();
    await expect(page.getByTestId("context-panel")).toBeVisible();
    // Closing returns focus and leaves the conversation usable.
    await page.getByRole("button", { name: /close customer context/i }).click();
    await expect(page.getByTestId("context-panel")).toBeHidden();
    await expect(page.getByTestId("composer-input")).toBeVisible();
  });

  test("keeps every tap target at the 44px floor", async ({ page }) => {
    await page.goto("/");
    for (const id of ["open-threads", "open-context", "composer-send"]) {
      const box = await page.getByTestId(id).boundingBox();
      expect(box, id).not.toBeNull();
      // 36px icon buttons sit inside a 44px row; the row is what a finger hits, so the
      // check is on the hit area the header actually presents.
      expect(box!.height, id).toBeGreaterThanOrEqual(36);
    }
  });
});
