import { expect } from '@playwright/test';

export async function choose(locator, value) {
  const page = locator.page();
  locator = locator.and(page.getByRole('combobox'));
  await locator.locator('xpath=ancestor::div[contains(concat(" ", @class, " "), " el-select ")][1]').click();
  const list = page.locator(`[id=${JSON.stringify(await locator.getAttribute('aria-controls'))}]`);
  await expect(list).toBeVisible();
  const options = list.getByRole('option');
  const option = typeof value === 'object'
    ? options.filter({ hasText: value.label }).filter({ visible: true })
    : list.locator(`[role="option"][data-ui-value=${JSON.stringify(String(value))}]`);
  await expect(option).toHaveCount(1);
  await option.click();
  await expect(list).not.toBeVisible();
}

export async function optionValues(locator) {
  const page = locator.page();
  locator = locator.and(page.getByRole('combobox'));
  await locator.locator('xpath=ancestor::div[contains(concat(" ", @class, " "), " el-select ")][1]').click();
  const list = page.locator(`[id=${JSON.stringify(await locator.getAttribute('aria-controls'))}]`);
  await expect(list).toBeVisible();
  const values = await list.locator('[role="option"]:not(.is-disabled)').evaluateAll(items => items.map(item => item.getAttribute('data-ui-value')));
  await locator.press('Escape');
  await expect(list).not.toBeVisible();
  return values;
}

export async function setChecked(locator, checked = true) {
  if (await locator.isChecked() !== checked) {
    const label = locator.locator('xpath=ancestor::label[contains(concat(" ", @class, " "), " el-checkbox ")][1]');
    if (await label.count()) await label.click();
    else await locator.setChecked(checked);
  }
  await expect(locator).toBeChecked({ checked });
}
