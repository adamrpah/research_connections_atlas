import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const feedback = sqliteTable("feedback", {
  id: text("id").primaryKey(),
  targetType: text("target_type").notNull(),
  targetId: text("target_id").notNull(),
  targetLabel: text("target_label").notNull(),
  feedbackCategory: text("feedback_category").notNull(),
  feedbackType: text("feedback_type").notNull(),
  comment: text("comment").notNull(),
  suggestedValue: text("suggested_value"),
  contactEmail: text("contact_email"),
  pageUrl: text("page_url"),
  datasetVersion: text("dataset_version").notNull(),
  status: text("status").notNull().default("new"),
  createdAt: integer("created_at", { mode: "timestamp_ms" }).notNull(),
});
