import removeMd from 'remove-markdown';

/**
 * Convert Markdown to plain text
 * Uses remove-markdown library for proper Markdown parsing
 */
export function markdownToPlainText(markdown: string): string {
  if (!markdown) return '';

  const plainText = removeMd(markdown, {
    gfm: true,
    useImgAltText: true,
    stripListLeaders: true,
  });

  // Additional post-processing to remove GFM table separator lines (e.g. |---|)
  // that remove-markdown sometimes leaves behind.
  return plainText
    .replace(/\n\|?[\s|:-]+\|?\s*(?=\n|$)/g, '\n')
    .trim();
}

// Circle emoji the generator uses with Western semantics (🔴 down / 🟢 up),
// which conflict with the A-share red=up / green=down convention.
const UPDOWN_CIRCLE_EMOJI = /[\u{1F534}\u{1F7E2}\u{1F7E1}]/gu; // 🔴 🟢 🟡

/**
 * Collapse Markdown into a single clean plain-text line for summary cards that
 * render generated content as plain text (otherwise raw `#`/`**`/`>` leaks).
 * Builds on markdownToPlainText, then flattens literal "\n" and whitespace.
 */
export function markdownToSummaryText(markdown?: string | null, maxLen?: number): string {
  if (!markdown) return '';
  let text = markdownToPlainText(markdown.replace(/\\n/g, ' '))
    .replace(/\s+/g, ' ')
    .trim();
  if (maxLen && text.length > maxLen) {
    text = `${text.slice(0, maxLen).trimEnd()}…`;
  }
  return text;
}

/**
 * Normalize Markdown for rendering (keeps structure): convert literal "\n" to
 * real newlines, collapse 3+ blank lines, and drop the Western up-down circle
 * emoji so the rendered原文 doesn't impose a conflicting color convention
 * (direction is still conveyed by the +/- numbers).
 */
export function sanitizeReportMarkdown(markdown?: string | null): string {
  if (!markdown) return '';
  return markdown
    .replace(/\\n/g, '\n')
    .replace(/\r\n/g, '\n')
    .replace(UPDOWN_CIRCLE_EMOJI, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
