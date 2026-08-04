import { env } from "cloudflare:workers";

const CATEGORIES: Record<string, Set<string>> = {
  topic_quality: new Set(["incorrect_topic", "topic_too_broad", "topic_too_narrow", "unclear_label", "incorrect_description", "suggested_topic"]),
  attribution_error: new Set(["wrong_faculty", "missing_faculty", "duplicate_faculty", "name_error", "wrong_publication"]),
  metadata_error: new Set(["title", "year", "doi", "authors", "abstract", "url"]),
};

type FeedbackPayload = {
  targetType?: string;
  targetId?: string;
  targetLabel?: string;
  feedbackCategory?: string;
  feedbackType?: string;
  comment?: string;
  suggestedValue?: string;
  contactEmail?: string;
  pageUrl?: string;
  datasetVersion?: string;
  website?: string;
};

function clean(value: unknown, max: number) {
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

async function ensureSchema(db: D1Database) {
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS feedback (
      id TEXT PRIMARY KEY,
      target_type TEXT NOT NULL,
      target_id TEXT NOT NULL,
      target_label TEXT NOT NULL,
      feedback_category TEXT NOT NULL,
      feedback_type TEXT NOT NULL,
      comment TEXT NOT NULL,
      suggested_value TEXT,
      contact_email TEXT,
      page_url TEXT,
      dataset_version TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'new',
      created_at INTEGER NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS feedback_target_idx ON feedback(target_type, target_id)"),
    db.prepare("CREATE INDEX IF NOT EXISTS feedback_created_idx ON feedback(created_at)"),
  ]);
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as FeedbackPayload;
    if (body.website) return Response.json({ ok: true });
    const targetType = clean(body.targetType, 32);
    const targetId = clean(body.targetId, 128);
    const targetLabel = clean(body.targetLabel, 300);
    const category = clean(body.feedbackCategory, 64);
    const feedbackType = clean(body.feedbackType, 64);
    const comment = clean(body.comment, 4000);
    if (!new Set(["faculty", "publication", "topic", "edge"]).has(targetType) || !targetId || !targetLabel || !comment || !CATEGORIES[category]?.has(feedbackType)) {
      return Response.json({ error: "Please complete all required feedback fields." }, { status: 400 });
    }
    const email = clean(body.contactEmail, 254);
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return Response.json({ error: "Please enter a valid email or leave it blank." }, { status: 400 });
    }
    await ensureSchema(env.DB);
    const id = crypto.randomUUID();
    await env.DB.prepare(`INSERT INTO feedback
      (id, target_type, target_id, target_label, feedback_category, feedback_type, comment, suggested_value, contact_email, page_url, dataset_version, status, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)`)
      .bind(id, targetType, targetId, targetLabel, category, feedbackType, comment,
        clean(body.suggestedValue, 2000) || null, email || null, clean(body.pageUrl, 1000) || null,
        clean(body.datasetVersion, 64) || "1.0.0", Date.now()).run();
    return Response.json({ ok: true, id }, { status: 201 });
  } catch (error) {
    console.error("Feedback submission failed", error);
    return Response.json({ error: "Feedback could not be saved. Please try again." }, { status: 500 });
  }
}

export async function GET(request: Request) {
  await ensureSchema(env.DB);
  const authorization = request.headers.get("authorization") ?? "";
  const adminKey = (env as unknown as { FEEDBACK_ADMIN_KEY?: string }).FEEDBACK_ADMIN_KEY;
  if (new URL(request.url).searchParams.get("export") === "attribution") {
    if (!adminKey || authorization !== `Bearer ${adminKey}`) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }
    const result = await env.DB.prepare(`SELECT id, target_type, target_id, target_label,
      feedback_category, feedback_type, comment, suggested_value, page_url,
      dataset_version, status, created_at
      FROM feedback WHERE feedback_category = 'attribution_error'
      ORDER BY created_at ASC`).all();
    return Response.json({ feedback: result.results });
  }
  const result = await env.DB.prepare("SELECT feedback_category, COUNT(*) AS count FROM feedback GROUP BY feedback_category").all();
  return Response.json({ counts: result.results });
}
