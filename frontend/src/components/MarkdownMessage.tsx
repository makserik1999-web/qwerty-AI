import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'

interface MarkdownMessageProps {
  content: string
}

/**
 * remark-math only treats `$$` as *display* math when the delimiters sit on
 * their own lines. The model usually writes a block formula on a single line
 * (`$$\int f(x)\,dx$$`), which would otherwise typeset as small inline math.
 * Expand those onto separate lines so they render as centered display math.
 */
const normalizeDisplayMath = (text: string): string =>
  text.replace(/^([ \t]*)\$\$[ \t]*(.+?)[ \t]*\$\$[ \t]*$/gm, '$1$$$$\n$2\n$1$$$$')

/**
 * Renders assistant explanations as formatted Markdown with typeset math.
 *
 * The model emits Markdown (**bold**, bullet lists, ### headings) and LaTeX
 * math in both inline ($...$) and block ($$...$$) delimiters. remark-math
 * parses the math, rehype-katex typesets it.
 *
 * This is what a real answer renders through, rather than the `blocks` shape
 * the prototype used. The model writes prose with formulas in it, and cutting
 * that into paragraph/formula/step by guessing would misfile lines that a
 * markdown parser already handles correctly - and would lose the formulas,
 * which is the half that most needs to survive.
 */
export function MarkdownMessage({ content }: MarkdownMessageProps) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
      >
        {normalizeDisplayMath(content)}
      </ReactMarkdown>
    </div>
  )
}
