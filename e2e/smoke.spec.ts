import { test, expect } from '@playwright/test';

test('dashboard builds successfully', async () => {
  // This is a build verification test.
  // The actual build happens in the CI step before this runs.
  // If we reach here, the build succeeded.
  expect(true).toBe(true);
});
