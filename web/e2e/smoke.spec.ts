import { expect, test } from "@playwright/test";

/**
 * Real-browser validation against a real running backend. This is the first time the web app has
 * ever actually been opened in a browser (previous verification stopped at `next build` + unit
 * tests). What this deliberately does NOT cover: the Web Speech API (Chromium's bundled build has
 * no speech recognition backend and no real microphone is available in a headless/CI browser), so
 * the voice orb, wake word and hands-free mode remain unverified by this suite — see
 * docs/reports/phase-browser.md.
 */

function uniqueEmail() {
  return `pw-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@x.com`;
}

test("login page renders with no console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });

  await page.goto("/login");
  await expect(page.getByText("WENSDAY", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
});

test("a real user can register, land on the assistant page, and get a real reply", async ({ page }) => {
  const email = uniqueEmail();

  await page.goto("/login");
  await page.getByRole("button", { name: /New here\?/i }).click();
  await page.getByLabel("Name").fill("Madesh");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Create account" }).click();

  // real navigation to the assistant page after a real registration + auto-login
  await expect(page).toHaveURL("/", { timeout: 15_000 });
  await expect(page.getByText(/Vanakkam/i)).toBeVisible();

  // real typed chat turn through the real backend's offline rule engine (no LLM key configured)
  const input = page.getByPlaceholder(/Type in Tamil, English or Tanglish/i);
  await input.fill("Wensday, nalaiku 9 mani meeting remind pannu.");
  await input.press("Enter");

  // not { exact: true }: the reply bubble also contains a sibling <small> style badge ("Tanglish"),
  // so the element's full text content is the reply plus that badge concatenated
  await expect(page.getByText("Sure Madesh, nalaiku morning 9:00 AM-ku meeting reminder set panniten."))
    .toBeVisible({ timeout: 10_000 });
});

test("tasks page: a real task can be added through the real UI and appears in the list", async ({ page }) => {
  const email = uniqueEmail();
  await page.goto("/login");
  await page.getByRole("button", { name: /New here\?/i }).click();
  await page.getByLabel("Name").fill("Madesh");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/", { timeout: 15_000 });

  await page.goto("/tasks");
  await page.getByPlaceholder(/Add a task/i).fill("Buy milk (playwright)");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("Buy milk (playwright)")).toBeVisible({ timeout: 10_000 });
});

test("dashboard renders charts without console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });

  const email = uniqueEmail();
  await page.goto("/login");
  await page.getByRole("button", { name: /New here\?/i }).click();
  await page.getByLabel("Name").fill("Madesh");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/", { timeout: 15_000 });

  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Day streak")).toBeVisible();
  expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
});

test("wrong password shows a real error from the real backend", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("nonexistent-user@x.com");
  await page.getByLabel("Password").fill("wrongpassword123");
  await page.getByRole("button", { name: "Sign in" }).click();
  // role=alert also matches Next.js's own route announcer (an empty, always-present a11y element),
  // so scope to the app's error styling rather than the ARIA role alone
  await expect(page.locator(".error")).toContainText(/invalid email or password/i, { timeout: 10_000 });
});
