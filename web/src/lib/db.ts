import postgres from "postgres";
import { drizzle } from "drizzle-orm/postgres-js";

const url = process.env.DATABASE_URL ?? "postgresql://postgres:postgres@localhost:5432/nfl_edge";
const globalForDb = globalThis as unknown as { pg?: ReturnType<typeof postgres> };
export const client = globalForDb.pg ?? postgres(url, { max: 5, prepare: false });
if (process.env.NODE_ENV !== "production") globalForDb.pg = client;
export const db = drizzle(client);
export const sql = client;
