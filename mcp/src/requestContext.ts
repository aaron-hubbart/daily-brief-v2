import { AsyncLocalStorage } from "node:async_hooks";

/**
 * Per-request auth context.
 *
 * This server no longer holds a secret of its own (see index.ts) — every
 * incoming /mcp POST carries its own caller's personal daily-brief API
 * token as its Authorization header, and that same token is what
 * dailyBriefClient.ts forwards to the webapp. AsyncLocalStorage threads
 * that token from the request handler through to the client without
 * needing to add a token parameter to every tool handler's signature, and
 * — unlike a module-level variable — stays correctly isolated across
 * concurrent requests from different users.
 */
export interface RequestContext {
  token: string;
}

export const requestContext = new AsyncLocalStorage<RequestContext>();

export function currentToken(): string {
  const store = requestContext.getStore();
  if (!store) {
    throw new Error("currentToken() called outside an active request context — this is a bug in index.ts's request handling, not a caller error");
  }
  return store.token;
}
