import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

export function renderMarkdown(src: string): string {
  if (!src) return ''
  const raw = md.render(src)
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
  })
}
