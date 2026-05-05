import type { Expense } from "@/lib/types";

export function normalizeReviewFlags(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => String(item ?? "").trim())
      .filter(Boolean);
  }

  if (typeof value !== "string") {
    return [];
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed
          .map((item) => String(item ?? "").trim())
          .filter(Boolean);
      }
    } catch {}
  }

  return trimmed
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function normalizeReviewBreakdown(value: unknown): Record<string, number> {
  if (!value) {
    return {};
  }

  if (typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(
      Object.entries(value)
        .map(([key, rawScore]) => [key, Number(rawScore)])
        .filter(([, score]) => Number.isFinite(score)),
    );
  }

  if (typeof value !== "string") {
    return {};
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }

  if (trimmed.startsWith("{")) {
    try {
      return normalizeReviewBreakdown(JSON.parse(trimmed));
    } catch {}
  }

  return Object.fromEntries(
    trimmed
      .split("|")
      .map((item) => item.split(":"))
      .filter(([key, rawScore]) => key && rawScore)
      .map(([key, rawScore]) => [key.trim(), Number(rawScore)])
      .filter(([, score]) => Number.isFinite(score)),
  );
}

export function normalizeExpenseReviewFields(expense: Expense): Expense {
  return {
    ...expense,
    review_breakdown: normalizeReviewBreakdown(expense.review_breakdown),
    review_flags: normalizeReviewFlags(expense.review_flags),
  };
}
