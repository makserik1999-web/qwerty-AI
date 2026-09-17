import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';

interface MarkdownMessageProps {
  content: string;
}

/**
 * remark-math only treats `$$` as *display* math when the delimiters sit on
 * their own lines. The model usually writes a block formula on a single line
 * (`$$\int f(x)\,dx$$`), which would otherwise typeset as small inline math.
 * Expand those onto separate lines so they render as centered display math.
 */
const normalizeDisplayMath = (text: string): string =>
  text.replace(/^([ \t]*)\$\$[ \t]*(.+?)[ \t]*\$\$[ \t]*$/gm, '$1$$$$\n$2\n$1$$$$');

/**
 * Renders assistant explanations as formatted Markdown with typeset math.
 *
 * The model emits Markdown (**bold**, bullet lists, ### headings) and LaTeX
 * math in both inline ($...$) and block ($$...$$) delimiters. remark-math
 * parses the math, rehype-katex typesets it.
 */
export const MarkdownMessage: React.FC<MarkdownMessageProps> = ({ content }) => (
  <div className="markdown-body text-sm leading-relaxed">
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
    >
      {normalizeDisplayMath(content)}
    </ReactMarkdown>
  </div>
);
