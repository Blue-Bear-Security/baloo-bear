// Skip husky install in CI or production
if (process.env.CI || process.env.NODE_ENV === "production") {
  process.exit(0);
}

const husky = (await import("husky")).default;
husky();
