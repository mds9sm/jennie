import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Search, FileText, ChevronRight, Printer } from 'lucide-react'
import { fetchJSON } from '../../api/client'

interface DocPage {
  slug: string
  title: string
  filename: string
}

interface DocContent {
  slug: string
  title: string
  content: string
}

interface TocEntry {
  id: string
  text: string
  level: number
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim()
}

function extractToc(markdown: string): TocEntry[] {
  const entries: TocEntry[] = []
  const lines = markdown.split('\n')
  for (const line of lines) {
    const match = line.match(/^(#{2,3})\s+(.+)/)
    if (match) {
      const level = match[1].length
      const text = match[2].replace(/[`*_~]/g, '').trim()
      entries.push({ id: slugify(text), text, level })
    }
  }
  return entries
}

function highlightText(text: string, query: string): React.ReactElement {
  if (!query.trim()) return <>{text}</>
  const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  const parts = text.split(regex)
  return (
    <>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-yellow-200 rounded px-0.5">{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  )
}

export default function DocsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [pages, setPages] = useState<DocPage[]>([])
  const [activeSlug, setActiveSlug] = useState<string | null>(null)
  const [content, setContent] = useState<DocContent | null>(null)
  const [toc, setToc] = useState<TocEntry[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [contentLoading, setContentLoading] = useState(false)
  const contentRef = useRef<HTMLDivElement>(null)

  // Fetch page list on mount
  useEffect(() => {
    fetchJSON<DocPage[]>('/docs/pages')
      .then((data) => {
        setPages(data)
        // Default to page from URL, or USER_GUIDE, or first page
        const urlSlug = searchParams.get('page')
        const defaultSlug =
          urlSlug && data.find((p) => p.slug === urlSlug)
            ? urlSlug
            : data.find((p) => p.slug === 'USER_GUIDE')?.slug || data[0]?.slug || null
        if (defaultSlug) setActiveSlug(defaultSlug)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch content when active page changes
  const fetchContent = useCallback(
    async (slug: string) => {
      setContentLoading(true)
      try {
        const data = await fetchJSON<DocContent>(`/docs/pages/${slug}`)
        setContent(data)
        setToc(extractToc(data.content))
        setSearchParams({ page: slug }, { replace: true })
      } catch {
        setContent(null)
        setToc([])
      } finally {
        setContentLoading(false)
      }
    },
    [setSearchParams]
  )

  useEffect(() => {
    if (activeSlug) fetchContent(activeSlug)
  }, [activeSlug, fetchContent])

  // Filter pages by search
  const filteredPages = search.trim()
    ? pages.filter(
        (p) =>
          p.title.toLowerCase().includes(search.toLowerCase()) ||
          p.slug.toLowerCase().includes(search.toLowerCase())
      )
    : pages

  function scrollToHeading(id: string) {
    const el = contentRef.current?.querySelector(`[id="${id}"]`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  function handlePrint() {
    window.print()
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        Loading documentation...
      </div>
    )
  }

  return (
    <div className="h-full flex print:block">
      {/* Left sidebar: page list + TOC */}
      <aside className="w-64 border-r border-gray-200 bg-gray-50 flex flex-col overflow-hidden print:hidden">
        {/* Search */}
        <div className="p-3 border-b border-gray-200">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search docs..."
              className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-genie-500 focus:border-genie-500"
            />
          </div>
        </div>

        {/* Page list */}
        <div className="flex-1 overflow-auto">
          <div className="px-3 pt-3 pb-1">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Pages</span>
          </div>
          <nav className="px-1 pb-2">
            {filteredPages.map((page) => (
              <button
                key={page.slug}
                onClick={() => setActiveSlug(page.slug)}
                className={`w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors text-left ${
                  activeSlug === page.slug
                    ? 'bg-genie-100 text-genie-800 font-medium'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`}
              >
                <FileText size={14} className="shrink-0" />
                <span className="truncate">
                  {search ? highlightText(page.title, search) : page.title}
                </span>
              </button>
            ))}
            {filteredPages.length === 0 && (
              <p className="px-3 py-2 text-xs text-gray-400">No matching pages</p>
            )}
          </nav>

          {/* Table of contents for active page */}
          {toc.length > 0 && activeSlug && (
            <div className="border-t border-gray-200 px-3 pt-3 pb-2">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                On this page
              </span>
              <nav className="mt-2 space-y-0.5">
                {toc.map((entry) => (
                  <button
                    key={entry.id}
                    onClick={() => scrollToHeading(entry.id)}
                    className="w-full flex items-center gap-1.5 text-left text-xs text-gray-500 hover:text-genie-700 transition-colors py-1 rounded"
                    style={{ paddingLeft: entry.level === 3 ? '1rem' : '0' }}
                  >
                    <ChevronRight size={10} className="shrink-0 text-gray-400" />
                    <span className="truncate">{entry.text}</span>
                  </button>
                ))}
              </nav>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto" ref={contentRef}>
        {contentLoading ? (
          <div className="flex items-center justify-center h-full text-gray-400">Loading...</div>
        ) : content ? (
          <div className="max-w-4xl mx-auto px-8 py-8">
            {/* Print button */}
            <div className="flex justify-end mb-4 print:hidden">
              <button
                onClick={handlePrint}
                className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
              >
                <Printer size={14} />
                Print
              </button>
            </div>

            {/* Markdown content */}
            <article className="prose prose-base max-w-none
              prose-headings:scroll-mt-4 prose-headings:font-semibold prose-headings:text-gray-900
              prose-h1:text-2xl prose-h1:border-b prose-h1:border-gray-200 prose-h1:pb-3 prose-h1:mb-6
              prose-h2:text-xl prose-h2:border-b prose-h2:border-gray-100 prose-h2:pb-2 prose-h2:mt-10 prose-h2:mb-4
              prose-h3:text-lg prose-h3:mt-8 prose-h3:mb-3
              prose-p:text-gray-700 prose-p:leading-7
              prose-li:text-gray-700 prose-li:leading-7
              prose-strong:text-gray-900
              prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:rounded-lg prose-pre:p-4 prose-pre:text-sm
              prose-code:text-pink-600 prose-code:bg-gray-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-code:before:content-none prose-code:after:content-none
              prose-pre:prose-code:bg-transparent prose-pre:prose-code:p-0 prose-pre:prose-code:text-gray-100
              prose-a:text-genie-600 prose-a:no-underline hover:prose-a:underline
              prose-table:border prose-table:border-gray-200 prose-table:rounded-lg prose-table:overflow-hidden prose-table:text-sm
              prose-thead:bg-gray-50 prose-th:px-4 prose-th:py-2.5 prose-th:text-left prose-th:font-semibold prose-th:text-gray-700 prose-th:border-b prose-th:border-gray-200
              prose-td:px-4 prose-td:py-2 prose-td:border-b prose-td:border-gray-100
              prose-tr:even:bg-gray-50/50
              prose-blockquote:border-l-4 prose-blockquote:border-genie-400 prose-blockquote:bg-genie-50 prose-blockquote:py-2 prose-blockquote:px-4 prose-blockquote:rounded-r-lg prose-blockquote:not-italic
              prose-hr:border-gray-200 prose-hr:my-8
              prose-img:rounded-lg
              prose-ol:list-decimal prose-ul:list-disc">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h2: ({ children, ...props }) => {
                    const text = typeof children === 'string' ? children : String(children)
                    const id = slugify(text)
                    return <h2 id={id} {...props}>{children}</h2>
                  },
                  h3: ({ children, ...props }) => {
                    const text = typeof children === 'string' ? children : String(children)
                    const id = slugify(text)
                    return <h3 id={id} {...props}>{children}</h3>
                  },
                }}
              >
                {content.content}
              </ReactMarkdown>
            </article>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400">
            Select a page to view
          </div>
        )}
      </main>
    </div>
  )
}
