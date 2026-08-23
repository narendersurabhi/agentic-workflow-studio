import ReactMarkdown from "react-markdown";

export function MarkdownContent({ content, streaming = false }: { content: string; streaming?: boolean }) {
  if (!content) return null;
  // During streaming show plain text to avoid flicker from partial parse trees
  // (e.g. unclosed code fences).  Once the turn is complete, render as markdown.
  if (streaming) {
    return <span className="whitespace-pre-wrap wrap-break-word">{content}</span>;
  }
  return (
    <ReactMarkdown
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
        h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-bold">{children}</h1>,
        h2: ({ children }) => <h2 className="mb-1.5 mt-3 text-sm font-bold">{children}</h2>,
        h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold">{children}</h3>,
        ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-0.5">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
        code: ({ children, className }) => {
          const isBlock = className?.startsWith("language-");
          return isBlock ? (
            <code className="block overflow-x-auto rounded-lg bg-black/30 px-3 py-2 font-mono text-[12px] leading-relaxed">
              {children}
            </code>
          ) : (
            <code className="rounded bg-black/25 px-1 py-0.5 font-mono text-[12px]">{children}</code>
          );
        },
        pre: ({ children }) => <pre className="mb-2 mt-1">{children}</pre>,
        blockquote: ({ children }) => (
          <blockquote className="mb-2 border-l-2 border-text-lo pl-3 text-text-md italic">
            {children}
          </blockquote>
        ),
        a: ({ href, children }) => (
          <a href={href} className="text-sky-400 underline hover:text-sky-300" target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        hr: () => <hr className="my-3 border-subtle" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

export default MarkdownContent;
