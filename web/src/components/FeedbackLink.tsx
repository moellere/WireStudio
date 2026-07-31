import { MessageSquarePlus } from "lucide-react";

const ISSUE_URL = "https://github.com/moellere/WireStudio/issues/new";

/**
 * Prefills the issue body with the bits that otherwise cost a round trip to
 * ask for. Everything here is shown in GitHub's form before the reporter
 * submits, so nothing is sent without them seeing it -- which is also why the
 * design itself is not included.
 */
export function issueUrl(version: string | null, boardId?: string | null): string {
  const body = [
    "",
    "",
    "---",
    `wirestudio ${version ? `v${version}` : "(version unknown)"}`,
    boardId ? `board: ${boardId}` : null,
    typeof navigator !== "undefined" ? `browser: ${navigator.userAgent}` : null,
  ]
    .filter((l) => l !== null)
    .join("\n");
  return `${ISSUE_URL}?body=${encodeURIComponent(body)}`;
}

export function FeedbackLink({
  version,
  boardId,
}: {
  version: string | null;
  boardId?: string | null;
}) {
  return (
    <a
      href={issueUrl(version, boardId)}
      target="_blank"
      rel="noreferrer noopener"
      className="flex items-center gap-1 rounded-md p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
      title="Report a bug or suggest a feature on GitHub"
      aria-label="Send feedback"
    >
      <MessageSquarePlus className="h-4 w-4" />
    </a>
  );
}
