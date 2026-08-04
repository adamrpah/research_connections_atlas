CREATE TABLE `feedback` (
	`id` text PRIMARY KEY NOT NULL,
	`target_type` text NOT NULL,
	`target_id` text NOT NULL,
	`target_label` text NOT NULL,
	`feedback_category` text NOT NULL,
	`feedback_type` text NOT NULL,
	`comment` text NOT NULL,
	`suggested_value` text,
	`contact_email` text,
	`page_url` text,
	`dataset_version` text NOT NULL,
	`status` text DEFAULT 'new' NOT NULL,
	`created_at` integer NOT NULL
);
