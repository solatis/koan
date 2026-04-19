import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function Md({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
