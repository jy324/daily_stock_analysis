import { describe, expect, it } from 'vitest';
import { markdownToPlainText, markdownToSummaryText, sanitizeReportMarkdown } from '../markdown';

describe('markdownToPlainText', () => {
  it('removes markdown syntax from links, images, and headings', () => {
    expect(
      markdownToPlainText('![logo](https://example.com/logo.png)\n[OpenAI](https://openai.com)\n# Title')
    ).toBe('logo\nOpenAI\nTitle');
  });

  it('removes common formatting markers while keeping readable content', () => {
    expect(
      markdownToPlainText('**Bold**\n> Quote\n1. Ordered item\n- Bullet item\n`inline code`')
    ).toBe('Bold\nQuote\nOrdered item\nBullet item\ninline code');
  });

  it('preserves underscores in variable names and identifiers', () => {
    // Underscore-separated words like variable names should NOT be treated as italic
    expect(markdownToPlainText('stock_code')).toBe('stock_code');
    expect(markdownToPlainText('user_name')).toBe('user_name');
    expect(markdownToPlainText('api_key_v2')).toBe('api_key_v2');
  });

  it('handles asterisk emphasis correctly', () => {
    // Single asterisk for italic
    expect(markdownToPlainText('*italic text*')).toBe('italic text');
    // Double asterisk for bold
    expect(markdownToPlainText('**bold text**')).toBe('bold text');
    // Combined emphasis
    expect(markdownToPlainText('***bold italic***')).toBe('bold italic');
  });

  it('handles underscore emphasis correctly when used as actual Markdown', () => {
    // Underscore emphasis only works at word boundaries or with whitespace
    expect(markdownToPlainText('_italic text_')).toBe('italic text');
    expect(markdownToPlainText('__bold text__')).toBe('bold text');
  });

  it('handles fenced code blocks', () => {
    expect(
      markdownToPlainText('```python\nprint("hello")\n```')
    ).toBe('print("hello")');
    expect(
      markdownToPlainText('```\nmulti\nline\ncode\n```')
    ).toBe('multi\nline\ncode');
  });

  it('handles tables with various content', () => {
    const input = `| Header | Value |
|--------|-------|
| cell1  | cell2 |
| **bold** | *italic* |`;
    const result = markdownToPlainText(input);
    expect(result).toContain('Header');
    expect(result).toContain('Value');
    expect(result).toContain('cell1');
    expect(result).toContain('cell2');
    expect(result).toContain('bold');
    expect(result).toContain('italic');
  });

  it('handles mixed content with headings, lists, and code', () => {
    const input = `# Main Title

## Section

Some text with **bold** and *italic*.

- Item 1
- Item 2

\`\`\`js
const x = 1;
\`\`\`

More text.`;
    const result = markdownToPlainText(input);
    expect(result).toContain('Main Title');
    expect(result).toContain('Section');
    expect(result).toContain('Some text with bold and italic');
    expect(result).toContain('Item 1');
    expect(result).toContain('Item 2');
    expect(result).toContain('const x = 1');
  });

  it('handles strikethrough in GFM', () => {
    expect(markdownToPlainText('~~deleted~~')).toBe('deleted');
  });

  it('handles blockquotes', () => {
    expect(markdownToPlainText('> This is a quote')).toBe('This is a quote');
    expect(markdownToPlainText('> Multi\n> line\n> quote')).toBe('Multi\nline\nquote');
  });

  it('returns empty string for empty or null input', () => {
    expect(markdownToPlainText('')).toBe('');
    expect(markdownToPlainText(null as unknown as string)).toBe('');
  });
});

describe('markdownToSummaryText', () => {
  it('flattens generated markdown into one clean line (no syntax, no newlines)', () => {
    const md = '# 🎯 大盘复盘\n## 2026-06-22 大盘复盘\n> 今日A股市场整体呈现**小幅上涨**态势。\n### 一、盘面总览';
    const out = markdownToSummaryText(md);
    expect(out).not.toMatch(/[#*>]/);
    expect(out).not.toContain('\n');
    expect(out).toContain('小幅上涨');
  });

  it('converts literal backslash-n and collapses whitespace', () => {
    expect(markdownToSummaryText('a\\nb   c')).toBe('a b c');
  });

  it('truncates with an ellipsis when maxLen is given', () => {
    expect(markdownToSummaryText('abcdefghij', 5)).toBe('abcde…');
  });

  it('returns empty for nullish input', () => {
    expect(markdownToSummaryText(undefined)).toBe('');
    expect(markdownToSummaryText(null)).toBe('');
  });
});

describe('sanitizeReportMarkdown', () => {
  it('converts literal backslash-n to real newlines', () => {
    expect(sanitizeReportMarkdown('line1\\nline2')).toBe('line1\nline2');
  });

  it('strips the Western up/down circle emoji (A-share color conflict)', () => {
    expect(sanitizeReportMarkdown('上证 🔴 -0.27%')).toBe('上证  -0.27%');
    expect(sanitizeReportMarkdown('深证 🟢 +0.05%')).toBe('深证  +0.05%');
    expect(sanitizeReportMarkdown('🟡 中性')).toBe('中性');
  });

  it('collapses 3+ blank lines to a single blank line', () => {
    expect(sanitizeReportMarkdown('a\n\n\n\nb')).toBe('a\n\nb');
  });

  it('keeps normal structure intact', () => {
    const md = '# 标题\n\n- 项目1\n- 项目2';
    expect(sanitizeReportMarkdown(md)).toBe('# 标题\n\n- 项目1\n- 项目2');
  });

  it('returns empty for nullish input', () => {
    expect(sanitizeReportMarkdown(undefined)).toBe('');
  });
});
