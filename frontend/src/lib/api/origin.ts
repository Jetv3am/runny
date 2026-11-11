/**
 * Where the FastAPI backend lives. Single source of truth, imported by
 * next.config.ts (proxy target) and by code that must bypass the proxy.
 */
export const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8100";
