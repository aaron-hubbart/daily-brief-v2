import { z } from "zod";
import { currentToken } from "./requestContext.js";

const API_BASE_URL = process.env.DAILY_BRIEF_API_BASE_URL;

if (!API_BASE_URL) {
  throw new Error("DAILY_BRIEF_API_BASE_URL environment variable is required");
}

export class DailyBriefApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: string
  ) {
    super(message);
    this.name = "DailyBriefApiError";
  }
}

async function request<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${currentToken()}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });

    const text = await res.text();

    if (!res.ok) {
      throw new DailyBriefApiError(
        `daily-brief API returned ${res.status} for ${path}`,
        res.status,
        text
      );
    }

    return text ? (JSON.parse(text) as T) : ({} as T);
  } finally {
    clearTimeout(timeout);
  }
}

// Mirrors the item shape defined in the daily-brief skill's references/item-sync.md
export const ItemLinkSchema = z.object({
  label: z.string(),
  url: z.string().url(),
  class: z.enum(["lbtn primary", "lbtn"])
});

export const ItemBadgeSchema = z.object({
  label: z.string(),
  class: z.enum(["bwarn", "bbad"])
});

export const BriefItemSchema = z.object({
  section: z.enum([
    "yesterday-meetings",
    "account-recap",
    "today",
    "action-items",
    "fyi",
    "customer-updates",
    "manager-update"
  ]).describe("Which of the 7 fixed brief sections this item belongs to"),
  item_key: z.string().describe("Stable key per the item-sync.md conventions, e.g. 'ym-0900-acmefin-triage' or 'action-{asana_gid}'"),
  item_type: z.enum(["checkable", "card", "fyi", "text-block"]),
  title: z.string().optional(),
  subtitle: z.string().optional(),
  badge: ItemBadgeSchema.optional(),
  links: z.array(ItemLinkSchema).optional(),
  content: z.record(z.unknown()).optional(),
  checked: z.boolean().optional(),
  display_order: z.number().int().optional()
});

export type BriefItem = z.infer<typeof BriefItemSchema>;

export async function upsertItem(
  briefDate: string,
  item: BriefItem
): Promise<{ ok: boolean; item_key: string }> {
  return request("/api/items/upsert", { brief_date: briefDate, ...item });
}

export async function batchUpsertItems(
  briefDate: string,
  briefType: "morning" | "midday" | "evening",
  items: BriefItem[]
): Promise<{ ok: boolean; count: number }> {
  return request("/api/items/batch-upsert", {
    brief_date: briefDate,
    brief_type: briefType,
    items
  });
}
