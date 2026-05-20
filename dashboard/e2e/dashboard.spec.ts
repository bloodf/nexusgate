import { test, expect } from "@playwright/test";
test("overview", async ({ page }) => { await page.goto("/"); await expect(page.getByText("NexusGate")).toBeVisible(); });
